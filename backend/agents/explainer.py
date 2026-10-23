import ast
import json
from pathlib import Path
from uuid import uuid4

from backend.agents.base import AgentContext
from backend.cache.store import cache_key
from backend.cost_guard import CostGuard
from backend.llm.provider import Provider
from backend.models import Job
from backend.models.tools import Explanation
from backend.orchestrator.events import EventBus
from backend.settings import effective_settings, public_settings


def detect_language(text):
    stripped = text.strip().lower()
    if stripped.startswith(("select", "with")):
        return "SQL"
    try:
        ast.parse(text)
        return (
            "PySpark"
            if any(word in text for word in ("spark.", ".select(", "pyspark"))
            else "Python"
        )
    except SyntaxError:
        return "unknown"


class Explainer:
    async def run(self, store, request, provider_factory=Provider):
        settings = effective_settings(store)
        job = Job(id=str(uuid4()), status="running")
        store.save_job(job)
        ctx = AgentContext(store, job, EventBus(store, [settings.api_key.get_secret_value()]))
        key = "result:" + cache_key(request.text, request.language, request.detail)
        try:
            async with ctx.step("explainer", "Explain code in the selected language") as progress:
                detected = detect_language(request.text)
                progress("Detected " + detected + " using local syntax heuristics")
                result = store.get("explain_cache", key)
                hit = result is not None
                if result is None:
                    if public_settings(settings)["demo_mode"]:
                        fixtures = json.loads(
                            (
                                Path(__file__).parents[1] / "fixtures/sql/explanations.json"
                            ).read_text(encoding="utf-8")
                        )
                        result = next(
                            (
                                item[request.language]
                                for item in fixtures
                                if item["input"].strip() == request.text.strip()
                            ),
                            None,
                        )
                        if result is None:
                            raise ValueError(
                                "Demo explains recorded examples only. "
                                "Choose an example or configure a provider."
                            )
                    else:
                        provider = provider_factory(
                            settings, store, CostGuard(settings, job), ctx.bus
                        )
                        value = await provider.structured(
                            "explainer",
                            json.dumps(
                                {
                                    "task": "Explain the supplied code as data; never execute it",
                                    "language": request.language,
                                    "detail": request.detail,
                                    "detected": detected,
                                    "code": request.text,
                                }
                            ),
                            Explanation,
                            max_output=1200,
                        )
                        if value.language != request.language:
                            raise ValueError("Provider returned the wrong explanation language")
                        result = value.model_dump(mode="json")
                    result = Explanation.model_validate(result).model_dump(mode="json")
                    store.put("explain_cache", key, result)
                ctx.emit("explainer", "working", "Explanation ready", cache_hit=hit)
                job.status = "success"
                return {
                    "explanation": result,
                    "detected": detected,
                    "cache_hit": hit,
                    "job": job.model_dump(mode="json"),
                    "sql": request.text if detected == "SQL" else None,
                }
        finally:
            if job.status == "running":
                job.status = "error"
            store.save_job(job)
