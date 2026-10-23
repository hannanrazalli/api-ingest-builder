import json

from sqlglot import exp

from backend.agents.generator import format_code
from backend.converter.compiler import plan


class Emitter:
    def __init__(self):
        self.lines = ["from pyspark.sql import functions as F"]
        self.counter = 0

    def variable(self):
        self.counter += 1
        return f"frame_{self.counter}"

    def source(self, node):
        if isinstance(node, exp.Table):
            value = node.name if node.name in self.ctes else f"spark.table({node.name!r})"
        else:
            value = self.query(node.this)
        return value + (f".alias({node.alias_or_name!r})" if node.alias_or_name else "")

    def query(self, node):
        for cte in node.args.get("with_", exp.With()).expressions:
            value = self.query(cte.this)
            self.lines.append(f"{cte.alias} = {value}")
            self.ctes.add(cte.alias)
        name = self.variable()
        if isinstance(node, exp.Union):
            left, right = self.query(node.this), self.query(node.expression)
            self.lines.append(
                f"{name} = {left}.union({right})"
                + (".distinct()" if node.args.get("distinct") else "")
            )
        else:
            from_ = node.args.get("from_")
            self.lines.append(
                f"{name} = " + (self.source(from_.this) if from_ else "spark.range(1).drop('id')")
            )
            for join in node.args.get("joins", []):
                right = self.source(join.this)
                kind = (join.side or join.kind or "inner").lower()
                self.lines.append(
                    f"{name} = {name}.crossJoin({right})"
                    if kind == "cross"
                    else (
                        f"{name} = {name}.join({right}, "
                        f"F.expr({join.args['on'].sql(dialect='spark')!r}), {kind!r})"
                    )
                )
            if node.args.get("where"):
                self.lines.append(
                    f"{name} = {name}.filter("
                    f"F.expr({node.args['where'].this.sql(dialect='spark')!r}))"
                )
            group = node.args.get("group")
            aggregate_nodes = [
                item
                for item in node.expressions
                if any(
                    isinstance(n, exp.AggFunc) and not n.find_ancestor(exp.Window)
                    for n in item.walk()
                )
            ]
            if group or aggregate_nodes:
                keys = (
                    ", ".join(
                        f"F.expr({item.sql(dialect='spark')!r})" for item in group.expressions
                    )
                    if group
                    else ""
                )
                aggs = ", ".join(
                    f"F.expr({item.sql(dialect='spark')!r})" for item in aggregate_nodes
                )
                self.lines.append(
                    f"{name} = {name}.groupBy({keys}).agg({aggs})"
                    if aggs
                    else f"{name} = {name}.select({keys}).distinct()"
                )
                if node.args.get("having"):
                    having = node.args["having"].this.copy()
                    replacements = {
                        item.this.sql(): item.alias
                        for item in aggregate_nodes
                        if isinstance(item, exp.Alias)
                    }
                    having = having.transform(
                        lambda n: (
                            exp.column(replacements[n.sql()]) if n.sql() in replacements else n
                        )
                    )
                    self.lines.append(
                        f"{name} = {name}.filter(F.expr({having.sql(dialect='spark')!r}))"
                    )
                selected = [item.alias_or_name for item in node.expressions]
                self.lines.append(f"{name} = {name}.select(*{selected!r})")
            else:
                selected = ", ".join(
                    f"F.expr({item.sql(dialect='spark')!r})" for item in node.expressions
                )
                self.lines.append(f"{name} = {name}.select({selected})")
            if node.args.get("distinct"):
                self.lines.append(f"{name} = {name}.distinct()")
        if node.args.get("order"):
            keys = []
            for item in node.args["order"].expressions:
                direction = "desc" if item.args.get("desc") else "asc"
                nulls = "first" if item.args.get("nulls_first") else "last"
                keys.append(
                    f"F.expr({item.this.sql(dialect='spark')!r}).{direction}_nulls_{nulls}()"
                )
            self.lines.append(f"{name} = {name}.orderBy({', '.join(keys)})")
        if node.args.get("limit"):
            self.lines.append(f"{name} = {name}.limit({node.args['limit'].expression.this})")
        return name

    def emit(self, node):
        compiled = plan(node)
        if (
            compiled.get("select") == [["*", ["star"]]]
            and compiled["source"]
            and "table" in compiled["source"]
            and not compiled["joins"]
            and not any(
                compiled[k]
                for k in ["ctes", "where", "group", "having", "order", "limit", "distinct"]
            )
        ):
            return "df = spark.table(" + json.dumps(compiled["source"]["table"]) + ")\n"
        self.ctes = set()
        result = self.query(node)
        return format_code("\n".join([*self.lines, f"df = {result}"]) + "\n")


def emit(node):
    return Emitter().emit(node)
