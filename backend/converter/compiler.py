"""Compile SQLGlot AST into a small, data-only relational plan."""

import re

import sqlglot
from sqlglot import exp


class Unsupported(ValueError):
    def __init__(self, node):
        self.fragment = node.sql() if isinstance(node, exp.Expression) else str(node)
        super().__init__("Unsupported SQL fragment: " + self.fragment[:160])


def identifier(name):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or name.startswith("_"):
        raise ValueError("Use simple non-private table/CTE identifiers")
    return name


def parse(sql, dialect="spark"):
    nodes = sqlglot.parse(sql, read=dialect)
    if len(nodes) != 1 or not isinstance(nodes[0], (exp.Select, exp.Union)):
        raise ValueError("Enter one read-only SELECT query")
    node = nodes[0]
    if len(list(node.walk())) > 1500:
        raise ValueError("Query is too complex")
    for table in node.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier) or table.db or table.catalog:
            raise ValueError("Only named input tables are allowed")
        identifier(table.name)
    for cte in node.find_all(exp.CTE):
        identifier(cte.alias)
    return node


def expression(node):
    if isinstance(node, exp.Alias):
        return expression(node.this)
    if isinstance(node, exp.Paren):
        return expression(node.this)
    if isinstance(node, exp.Column):
        return ["col", (node.table + "." if node.table else "") + node.name]
    if isinstance(node, exp.Star):
        return ["star"]
    if isinstance(node, exp.Literal):
        return [
            "lit",
            node.this
            if node.is_string
            else float(node.this)
            if "." in node.this
            else int(node.this),
        ]
    if isinstance(node, exp.Null):
        return ["lit", None]
    if isinstance(node, exp.Boolean):
        return ["lit", node.this]
    binary = {
        exp.Add: "add",
        exp.Sub: "sub",
        exp.Mul: "mul",
        exp.Div: "div",
        exp.Mod: "mod",
        exp.EQ: "eq",
        exp.NEQ: "ne",
        exp.GT: "gt",
        exp.GTE: "ge",
        exp.LT: "lt",
        exp.LTE: "le",
        exp.And: "and",
        exp.Or: "or",
        exp.Is: "is",
    }
    for cls, name in binary.items():
        if isinstance(node, cls):
            return [name, expression(node.this), expression(node.expression)]
    if isinstance(node, (exp.Not, exp.Neg)):
        return ["not" if isinstance(node, exp.Not) else "neg", expression(node.this)]
    if isinstance(node, exp.Between):
        return [
            "and",
            ["ge", expression(node.this), expression(node.args["low"])],
            ["le", expression(node.this), expression(node.args["high"])],
        ]
    if isinstance(node, exp.In):
        values = [expression(item) for item in node.expressions]
        if node.args.get("query"):
            return ["in_query", expression(node.this), plan(node.args["query"].this)]
        return ["in", expression(node.this), values]
    if isinstance(node, exp.Subquery):
        return ["scalar_query", plan(node.this)]
    if isinstance(node, exp.Case):
        return [
            "case",
            expression(node.this) if node.this else None,
            [[expression(i.this), expression(i.args["true"])] for i in node.args["ifs"]],
            expression(node.args["default"]) if node.args.get("default") else ["lit", None],
        ]
    if isinstance(node, exp.Cast):
        dtype = node.args["to"].sql().upper()
        if dtype not in {
            "INT",
            "BIGINT",
            "DOUBLE",
            "FLOAT",
            "TEXT",
            "STRING",
            "VARCHAR",
            "BOOLEAN",
            "DATE",
        }:
            raise Unsupported(node)
        return ["cast", expression(node.this), dtype]
    if isinstance(node, exp.Window):
        if node.args.get("alias"):
            raise Unsupported(node)
        spec = node.args.get("spec")
        bounds = None
        if spec:

            def bound(value, side):
                if value == "UNBOUNDED":
                    return None
                if value == "CURRENT ROW":
                    return 0
                if not isinstance(value, exp.Literal) or value.is_string:
                    raise Unsupported(spec)
                return int(value.this) * (-1 if str(side).upper() == "PRECEDING" else 1)

            bounds = [
                str(spec.args.get("kind")).upper(),
                bound(spec.args.get("start"), spec.args.get("start_side")),
                bound(spec.args.get("end"), spec.args.get("end_side")),
            ]
        return [
            "window",
            expression(node.this),
            [expression(i) for i in node.args.get("partition_by", [])],
            order(node.args.get("order")),
            bounds,
        ]
    aggregates = {
        exp.Sum: "sum",
        exp.Avg: "avg",
        exp.Count: "count",
        exp.Min: "min",
        exp.Max: "max",
    }
    for cls, name in aggregates.items():
        if isinstance(node, cls):
            arg = node.this
            distinct = isinstance(arg, exp.Distinct)
            if distinct:
                if len(arg.expressions) != 1:
                    raise Unsupported(node)
                arg = arg.expressions[0]
            return ["agg", name, expression(arg), distinct]
    for cls, name in {
        exp.RowNumber: "row_number",
        exp.Rank: "rank",
        exp.DenseRank: "dense_rank",
    }.items():
        if isinstance(node, cls):
            return [name]
    if isinstance(node, (exp.Lag, exp.Lead)):
        offset = node.args.get("offset")
        if offset and not isinstance(offset, exp.Literal):
            raise Unsupported(node)
        return [
            "lag" if isinstance(node, exp.Lag) else "lead",
            expression(node.this),
            int(offset.this) if offset else 1,
            expression(node.args["default"]) if node.args.get("default") else ["lit", None],
        ]
    if isinstance(node, (exp.Lower, exp.Upper, exp.Abs)):
        return [node.key, expression(node.this)]
    if isinstance(node, exp.Coalesce):
        return ["coalesce", *[expression(i) for i in [node.this, *node.expressions]]]
    if isinstance(node, (exp.Like, exp.ILike)):
        if not isinstance(node.expression, exp.Literal):
            raise Unsupported(node)
        return ["like", expression(node.this), node.expression.this, isinstance(node, exp.ILike)]
    raise Unsupported(node)


def order(node):
    return (
        [
            [expression(i.this), bool(i.args.get("desc")), bool(i.args.get("nulls_first"))]
            for i in node.expressions
        ]
        if node
        else []
    )


def source(node):
    if isinstance(node, exp.Table):
        return {"table": identifier(node.name), "alias": node.alias_or_name}
    if isinstance(node, exp.Subquery):
        return {"query": plan(node.this), "alias": node.alias}
    raise Unsupported(node)


def plan(node):
    ctes = [[cte.alias, plan(cte.this)] for cte in node.args.get("with_", exp.With()).expressions]
    if isinstance(node, exp.Union):
        return {
            "ctes": ctes,
            "union": [plan(node.this), plan(node.expression)],
            "distinct": bool(node.args.get("distinct")),
            "order": order(node.args.get("order")),
            "limit": limit(node),
        }
    if not isinstance(node, exp.Select):
        raise Unsupported(node)
    for key in ["qualify", "laterals", "connect", "windows", "offset", "into", "locks", "sample"]:
        if node.args.get(key):
            raise Unsupported(node.args[key])
    joins = []
    for join in node.args.get("joins", []):
        kind = (join.side or join.kind or "inner").lower()
        if kind not in {"inner", "left", "right", "full", "cross"} or join.args.get("using"):
            raise Unsupported(join)
        condition = expression(join.args["on"]) if join.args.get("on") else None
        if kind != "cross" and (
            not condition
            or condition[0] != "eq"
            or condition[1][0] != "col"
            or condition[2][0] != "col"
        ):
            raise Unsupported(join)
        joins.append({"source": source(join.this), "kind": kind, "on": condition})
    projections = [
        [i.alias_or_name or f"expression_{n + 1}", expression(i)]
        for n, i in enumerate(node.expressions)
    ]
    return {
        "ctes": ctes,
        "source": source(node.args["from_"].this) if node.args.get("from_") else None,
        "joins": joins,
        "where": expression(node.args["where"].this) if node.args.get("where") else None,
        "group": [expression(i) for i in node.args.get("group", exp.Group()).expressions],
        "having": expression(node.args["having"].this) if node.args.get("having") else None,
        "select": projections,
        "distinct": bool(node.args.get("distinct")),
        "order": order(node.args.get("order")),
        "limit": limit(node),
    }


def limit(node):
    value = node.args.get("limit")
    if value:
        number = value.expression
        if not isinstance(number, exp.Literal) or number.is_string or int(number.this) < 0:
            raise Unsupported(value)
        return int(number.this)
    return None
