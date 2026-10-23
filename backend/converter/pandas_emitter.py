import inspect
import pprint

from backend.agents.generator import format_code
from backend.converter import pandas_runtime
from backend.converter.compiler import plan


def emit(node):
    compiled = plan(node)
    if (
        not compiled["ctes"]
        and not compiled.get("union")
        and compiled["source"]
        and "table" in compiled["source"]
        and not compiled["joins"]
        and compiled["select"] == [["*", ["star"]]]
        and not any(compiled[k] for k in ["where", "group", "having", "order", "limit", "distinct"])
    ):
        return f"df = {compiled['source']['table']}.copy()\n"
    tables = sorted(
        {table.name for table in node.find_all(__import__("sqlglot").exp.Table)}
        - {cte.alias for cte in node.find_all(__import__("sqlglot").exp.CTE)}
    )
    code = inspect.getsource(pandas_runtime)
    # Named CTE variables remain visible in the output, matching SQL's scope.
    ctes = compiled.pop("ctes")
    mapping = "{" + ", ".join(repr(name) + ": " + name for name in tables) + "}"
    code += "\ntables = " + mapping + "\n"
    for name, query in ctes:
        code += f"{name} = _query({pprint.pformat(query, width=85)}, tables)\n"
        code += f"tables[{name!r}] = {name}\n"
    compiled["ctes"] = []
    code += "df = _query(" + pprint.pformat(compiled, width=85) + ", tables)\n"
    return format_code(code)
