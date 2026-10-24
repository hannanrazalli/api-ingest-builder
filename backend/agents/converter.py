import json
from uuid import uuid4

import sqlglot
from sqlglot import exp

from backend.agents.base import AgentContext
from backend.cache.store import cache_key
from backend.converter import pandas_emitter, pyspark_emitter
from backend.converter.compiler import Unsupported, parse, plan
from backend.cost_guard import CostGuard
from backend.llm.provider import Provider
from backend.models import Job
from backend.models.tools import FragmentResult
from backend.orchestrator.events import EventBus
from backend.settings import effective_settings


class Converter:
    async def run(self, store, request, provider_factory=Provider, *, job=None):
        settings = effective_settings(store)
        job = job or Job(id=str(uuid4()))
        job.status = "running"
        store.save_pending(job.id, "convert", request)
        store.save_job(job)
        ctx = AgentContext(store, job, EventBus(store, [settings.api_key.get_secret_value()]))
        key = "result:" + cache_key(request.sql, request.dialect, request.target)
        try:
            async with ctx.step("converter", "Convert SQL AST to DataFrame operations") as progress:
                cached = store.get("convert_cache", key)
                if cached:
                    job.status = "success"
                    ctx.emit("converter", "success", "Loaded cached conversion", cache_hit=True)
                    return {
                        **cached,
                        "job": job.model_copy(update={"status": "success"}).model_dump(mode="json"),
                        "cache_hit": True,
                    }
                node = parse(request.sql, request.dialect)
                fragments = []
                provider = provider_factory(settings, store, CostGuard(settings, job), ctx.bus)
                try:
                    plan(node)
                except Unsupported as error:
                    if not request.allow_llm:
                        job.status = "success"
                        return {
                            "job": job.model_dump(mode="json"),
                            "status": "unsupported",
                            "fragment": error.fragment,
                            "pyspark": None,
                            "pandas": None,
                            "llm_generated": [],
                            "cache_hit": False,
                        }
                    progress("Send only the unsupported expression and dialect to the provider")
                    response = await provider.structured(
                        "converter",
                        json.dumps(
                            {
                                "task": (
                                    "Rewrite this expression with standard SQL. "
                                    "No query, tables or statements."
                                ),
                                "fragment": error.fragment,
                                "dialect": request.dialect,
                            }
                        ),
                        FragmentResult,
                    )
                    replacement = sqlglot.parse_one(response.sql_expression, read=request.dialect)
                    if any(
                        isinstance(n, (exp.Query, exp.Table, exp.Command))
                        for n in replacement.walk()
                    ):
                        raise ValueError("Fallback must return one expression only") from None
                    from backend.converter.compiler import expression

                    expression(replacement)
                    fragment = error.fragment
                    node = node.transform(
                        lambda n: replacement.copy() if n.sql() == fragment else n
                    )
                    plan(node)
                    fragments.append(error.fragment)
                value = {
                    "status": "success",
                    "pyspark": pyspark_emitter.emit(node)
                    if request.target in {"both", "pyspark"}
                    else None,
                    "pandas": pandas_emitter.emit(node)
                    if request.target in {"both", "pandas"}
                    else None,
                    "llm_generated": fragments,
                    "cache_hit": False,
                }
                if fragments:
                    for target in ("pyspark", "pandas"):
                        if value[target]:
                            value[target] = (
                                "# LLM-generated expression rewrite; review before running\n"
                                + value[target]
                            )
                store.put("convert_cache", key, value)
                progress("Syntax validated; deterministic output ready")
                job.status = "success"
                return {**value, "job": job.model_dump(mode="json")}
        finally:
            if job.status == "running":
                job.status = "error"
            job.budget_ready = job.status == "waiting"
            store.save_job(job)
