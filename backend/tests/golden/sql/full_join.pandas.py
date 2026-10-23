"Standalone pandas operations for the compiler's data-only plans. No SQL/eval."

import operator
import re

import pandas as pd


def _column(frame, name):
    if name in frame:
        return frame[name]
    matches = [c for c in frame if c.rsplit(".", 1)[-1] == name]
    if len(matches) != 1:
        raise ValueError("Missing or ambiguous column: " + name)
    return frame[matches[0]]


def _series(value, frame):
    return value if isinstance(value, pd.Series) else pd.Series(value, index=frame.index)


def _scalar(value):
    return value.iloc[0] if isinstance(value, pd.Series) and len(value) else value


def _expr(node, frame, tables):
    op, *args = node
    if op == "lit":
        return args[0]
    if op == "col":
        return _column(frame, args[0])
    if op == "star":
        return pd.Series(1, index=frame.index)
    if op == "window":
        return _window(args, frame, tables)
    if op in {"in_query", "scalar_query"}:
        result = _query(args[-1], tables)
        if op == "scalar_query":
            if result.shape != (1, 1):
                raise ValueError("Scalar subquery must return one value")
            return result.iloc[0, 0]
        return _series(_expr(args[0], frame, tables), frame).isin(result.iloc[:, 0])
    if op == "case":
        base, branches, default = args
        output = _series(_expr(default, frame, tables), frame).copy()
        for test, value in reversed(branches):
            cond = _expr(test, frame, tables)
            if base is not None:
                cond = _expr(base, frame, tables) == cond
            mask = _series(cond, frame).fillna(False).astype(bool)
            output = output.where(~mask, _series(_expr(value, frame, tables), frame))
        return output
    if op == "agg":
        name, expression, distinct = args
        values = _series(_expr(expression, frame, tables), frame)
        if distinct:
            values = values.drop_duplicates()
        if name == "count":
            return int(values.count())
        if name == "sum":
            return values.sum(min_count=1)
        return getattr(values, {"avg": "mean", "min": "min", "max": "max"}[name])()
    value = _expr(args[0], frame, tables)
    if op == "cast":
        dtype = args[1]
        if dtype == "DATE":
            return pd.to_datetime(value).dt.date
        return _series(value, frame).astype(
            {
                "INT": "Int64",
                "BIGINT": "Int64",
                "DOUBLE": "Float64",
                "FLOAT": "Float64",
                "TEXT": "string",
                "STRING": "string",
                "VARCHAR": "string",
                "BOOLEAN": "boolean",
            }[dtype]
        )
    if op == "coalesce":
        output = _series(value, frame)
        for item in args[1:]:
            output = output.fillna(_expr(item, frame, tables))
        return output
    if op in {"lower", "upper"}:
        return getattr(_series(value, frame).astype("string").str, op)()
    if op == "abs":
        return abs(value)
    if op == "like":
        pattern = "".join(".*" if c == "%" else "." if c == "_" else re.escape(c) for c in args[1])
        return _series(value, frame).astype("string").str.fullmatch(pattern, case=not args[2])
    if op == "in":
        return _series(value, frame).isin([_expr(item, frame, tables) for item in args[1]])
    if op == "neg":
        return -value
    if op == "not":
        return ~_series(value, frame).astype("boolean")
    right = _expr(args[1], frame, tables)
    if op == "is":
        return _series(value, frame).isna() if right is None else value == right
    functions = {
        "add": operator.add,
        "sub": operator.sub,
        "mul": operator.mul,
        "div": operator.truediv,
        "mod": operator.mod,
        "eq": operator.eq,
        "ne": operator.ne,
        "gt": operator.gt,
        "ge": operator.ge,
        "lt": operator.lt,
        "le": operator.le,
        "and": operator.and_,
        "or": operator.or_,
    }
    if op in {"and", "or"}:
        return functions[op](
            _series(value, frame).astype("boolean"), _series(right, frame).astype("boolean")
        )
    if op in {"eq", "ne", "gt", "ge", "lt", "le"}:
        left_s, right_s = _series(value, frame), _series(right, frame)
        result = functions[op](left_s, right_s).astype("boolean")
        return result.mask(left_s.isna() | right_s.isna(), pd.NA)
    return functions[op](value, right)


def _sort(frame, ordering, tables):
    result = frame.copy()
    # Stable sorts from the last key preserve SQL's per-key direction/null ordering.
    for index, (expr, desc, nulls_first) in reversed(list(enumerate(ordering))):
        key = f"__sort_{index}"
        if expr[0] == "lit" and isinstance(expr[1], int):
            result[key] = result.iloc[:, expr[1] - 1]
        else:
            result[key] = _expr(expr, result, tables)
        result = result.sort_values(
            key, ascending=not desc, na_position="first" if nulls_first else "last", kind="stable"
        ).drop(columns=key)
    return result


def _window(args, frame, tables):
    function, partitions, ordering, bounds = args
    work = frame.copy()
    keys = []
    for index, expr in enumerate(partitions):
        key = f"__part_{index}"
        work[key] = _expr(expr, work, tables)
        keys.append(key)
    groups = work.groupby(keys, dropna=False, sort=False) if keys else [(None, work)]
    output = pd.Series(index=frame.index, dtype=object)
    for _, group in groups:
        group = _sort(group, ordering, tables)
        n = len(group)
        values = (
            _series(
                _expr(function[2] if function[0] == "agg" else function[1], group, tables), group
            )
            if function[0] in {"agg", "lag", "lead"}
            else None
        )
        sort_values = [
            tuple(_scalar(_expr(expr, group.iloc[[i]], tables)) for expr, *_ in ordering)
            for i in range(n)
        ]
        dense, rank, prior = 0, 1, None
        for i, idx in enumerate(group.index):
            if function[0] == "row_number":
                answer = i + 1
            elif function[0] in {"rank", "dense_rank"}:
                current = sort_values[i]
                if i == 0 or current != prior:
                    dense += 1
                    rank = i + 1
                answer = rank if function[0] == "rank" else dense
                prior = current
            elif function[0] in {"lag", "lead"}:
                j = i + function[2] * (-1 if function[0] == "lag" else 1)
                answer = (
                    values.iloc[j]
                    if 0 <= j < n
                    else _scalar(_expr(function[3], group.iloc[[i]], tables))
                )
            else:
                kind, start, end = bounds or (
                    ["RANGE", None, 0] if ordering else ["ROWS", None, None]
                )
                if kind == "ROWS":
                    lo, hi = (
                        (0 if start is None else max(0, i + start)),
                        (n if end is None else min(n, i + end + 1)),
                    )
                    subset = values.iloc[lo:hi]
                else:
                    if not ordering:
                        subset = values
                    elif start is None and end == 0:
                        # Peer-inclusive default RANGE frame.
                        hi = i + 1
                        while hi < n and sort_values[hi] == sort_values[i]:
                            hi += 1
                        subset = values.iloc[:hi]
                    else:
                        if len(ordering) != 1:
                            raise ValueError("Bounded RANGE needs one numeric ordering key")
                        current = sort_values[i][0]
                        direction = -1 if ordering[0][1] else 1
                        positions = [
                            j
                            for j, row in enumerate(sort_values)
                            if (start is None or direction * (row[0] - current) >= start)
                            and (end is None or direction * (row[0] - current) <= end)
                        ]
                        subset = values.iloc[positions]
                if function[3]:
                    subset = subset.drop_duplicates()
                answer = (
                    subset.sum(min_count=1)
                    if function[1] == "sum"
                    else subset.count()
                    if function[1] == "count"
                    else getattr(subset, {"avg": "mean", "min": "min", "max": "max"}[function[1]])()
                )
            output.loc[idx] = answer
    return output.infer_objects()


def _source(source, tables):
    if source is None:
        return pd.DataFrame(index=[0])
    frame = tables[source["table"]].copy() if "table" in source else _query(source["query"], tables)
    alias = source["alias"]
    if alias:
        frame.columns = [alias + "." + str(c) for c in frame.columns]
    return frame.reset_index(drop=True)


def _has_aggregate(node):
    if not isinstance(node, list) or not node:
        return False
    if node[0] == "window":
        return False
    return node[0] == "agg" or any(_has_aggregate(item) for item in node if isinstance(item, list))


def _query(plan, tables):
    tables = dict(tables)
    for name, query in plan["ctes"]:
        tables[name] = _query(query, tables)
    if "union" in plan:
        left, right = [_query(item, tables) for item in plan["union"]]
        right.columns = left.columns
        frame = pd.concat([left, right], ignore_index=True)
        if plan["distinct"]:
            frame = frame.drop_duplicates()
        return (
            _sort(frame, plan["order"], tables).head(plan["limit"]).reset_index(drop=True)
            if plan["limit"] is not None
            else _sort(frame, plan["order"], tables).reset_index(drop=True)
        )
    frame = _source(plan["source"], tables)
    for join in plan["joins"]:
        right = _source(join["source"], tables)
        if join["kind"] == "cross":
            frame = frame.merge(right, how="cross")
        else:
            left_key, right_key = join["on"][1][1], join["on"][2][1]
            if left_key not in frame and right_key in frame:
                left_key, right_key = right_key, left_key
            left_key = _column(frame, left_key).name
            right_key = _column(right, right_key).name
            # SQL NULL never equals NULL. Unique sentinels keep outer rows intact.
            left_tmp, right_tmp = frame.copy(), right.copy()
            left_tmp["__join_key"] = (
                left_tmp[left_key].astype(object).where(left_tmp[left_key].notna(), object())
            )
            right_tmp["__join_key"] = (
                right_tmp[right_key].astype(object).where(right_tmp[right_key].notna(), object())
            )
            frame = left_tmp.merge(
                right_tmp, on="__join_key", how="outer" if join["kind"] == "full" else join["kind"]
            ).drop(columns="__join_key")
        frame = frame.reset_index(drop=True)
    if plan["where"]:
        frame = frame.loc[
            _series(_expr(plan["where"], frame, tables), frame).fillna(False).astype(bool)
        ].copy()
    grouped = bool(plan["group"]) or any(_has_aggregate(expr) for _, expr in plan["select"])
    if grouped:
        keys = []
        for i, expr in enumerate(plan["group"]):
            key = f"__group_{i}"
            frame[key] = _expr(expr, frame, tables)
            keys.append(key)
        groups = frame.groupby(keys, dropna=False, sort=False) if keys else [(None, frame)]
        rows = []
        for _, group in groups:
            row = {name: _scalar(_expr(expr, group, tables)) for name, expr in plan["select"]}
            if plan["having"]:
                test_frame = group.copy()
                for name, value in row.items():
                    test_frame[name] = value
                test = _scalar(_expr(plan["having"], test_frame, tables))
                if pd.isna(test) or not test:
                    continue
            rows.append(row)
        result = pd.DataFrame(rows, columns=[name for name, _ in plan["select"]])
    else:
        # ORDER BY may reference columns omitted from SELECT.
        alias_frame = frame.copy()
        for name, expr in plan["select"]:
            if expr[0] != "star":
                alias_frame[name] = _expr(expr, frame, tables)
        if plan["order"] and not any(expr[0] == "lit" for expr, *_ in plan["order"]):
            frame = _sort(alias_frame, plan["order"], tables)
        result = pd.DataFrame(index=frame.index)
        for name, expr in plan["select"]:
            if expr[0] == "star":
                for column in frame.columns:
                    if column not in [n for n, e in plan["select"] if e[0] != "star"]:
                        result[column.rsplit(".", 1)[-1]] = frame[column]
            else:
                result[name] = _expr(expr, frame, tables)
    if grouped or any(expr[0] == "lit" for expr, *_ in plan["order"]):
        result = _sort(result, plan["order"], tables)
    if plan["distinct"]:
        result = result.drop_duplicates()
    if plan["limit"] is not None:
        result = result.head(plan["limit"])
    return result.reset_index(drop=True)


tables = {"other": other, "source": source}
df = _query(
    {
        "ctes": [],
        "distinct": False,
        "group": [],
        "having": None,
        "joins": [
            {
                "kind": "full",
                "on": ["eq", ["col", "s.id"], ["col", "o.id"]],
                "source": {"alias": "o", "table": "other"},
            }
        ],
        "limit": None,
        "order": [],
        "select": [["left_id", ["col", "s.id"]], ["right_id", ["col", "o.id"]]],
        "source": {"alias": "s", "table": "source"},
        "where": None,
    },
    tables,
)
