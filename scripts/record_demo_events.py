"""Record actual offline fixture pipeline events; never invoke a real provider."""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.cache.store import Store
from backend.fixtures.runtime import ROOT, FixtureHTTP
from backend.models import Settings
from backend.models.research import ResearchRequest
from backend.orchestrator.research import ResearchPipeline
from backend.tests.test_research import mocked_provider


async def record():
    destination = ROOT / "demo_events"
    destination.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="aib-demo-record-") as directory:
        for scenario, fixture, options in [
            ("cache_miss", "coingecko", {}), ("cache_hit", "coingecko", {}),
            ("openapi", "frankfurter", {}), ("repair", "coingecko", {"failures": 2}),
            ("docs_not_found", "frankfurter", {"not_found": True}),
            ("budget_blocked", "coingecko", {}),
        ]:
            store = Store(Path(directory) / (scenario + ".sqlite3"))
            store.save_settings(Settings(api_key="fixture-provider-key", model_fast="fixture-fast",
                                model_smart="fixture-smart", max_llm_calls=0 if scenario == "budget_blocked" else 3))
            pipeline = ResearchPipeline(store, fetcher=FixtureHTTP(fixture, **options),
                                        provider_factory=mocked_provider(fixture))
            request = ResearchRequest(url="coingecko.com" if fixture == "coingecko" else "frankfurter.dev", demo=False,
                                      api_key="fixture-target-key", api_key_host="api.coingecko.com" if fixture == "coingecko" else "api.frankfurter.dev")
            if scenario == "cache_hit":
                await pipeline.run(request)
            result = await pipeline.run(request)
            records=[]
            for i, (_, event) in enumerate(store.events(result.job.id)):
                value=event.model_dump(mode="json")
                value.update(job_id=f"{fixture}-{scenario}", ts=1792713600 + i * .4)
                records.append(value)
            (destination / f"{fixture}_{scenario}.json").write_text(json.dumps(records,indent=2),encoding="utf-8")
            print(f"{scenario}: {result.status}, {result.job.calls} LLM mock calls, {len(records)} events")


if __name__ == "__main__":
    asyncio.run(record())
