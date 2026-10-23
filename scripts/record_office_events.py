"""Record deterministic modules, then combine with the offline mocked repair/cache logs."""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.agents.base import AgentContext
from backend.agents.converter import Converter
from backend.agents.explainer import Explainer
from backend.agents.generator import Generator
from backend.cache.store import Store
from backend.models.generation import GenerationOptions
from backend.models.research import ResearchRequest
from backend.models.tools import ConvertRequest, ExplainRequest
from backend.orchestrator.events import EventBus
from backend.orchestrator.research import ResearchPipeline

async def record():
    root=Path(__file__).resolve().parents[1]/"backend/fixtures/demo_events"
    values=json.loads((root/"coingecko_repair.json").read_text())
    values+=json.loads((root/"coingecko_cache_hit.json").read_text())
    with tempfile.TemporaryDirectory(prefix="aib-office-") as directory:
        store=Store(Path(directory)/"record.sqlite3")
        result=await ResearchPipeline(store).run(ResearchRequest(url="frankfurter.dev",demo=True))
        context=AgentContext(store,result.job,EventBus(store))
        await Generator().run(context,result.spec,GenerationOptions(),result.profile)
        converted=await Converter().run(store,ConvertRequest(sql="select * from source"))
        explained=await Explainer().run(store,ExplainRequest(text="select * from source"))
        for job in [result.job.id,converted["job"]["id"],explained["job"]["id"]]:
            for _,event in store.events(job):values.append(event.model_dump(mode="json"))
    for index,value in enumerate(values):
        value.update(job_id="office-full-recording",ts=1792713600+index*.4)
    (root/"office_full.json").write_text(json.dumps(values,indent=2),encoding="utf-8",newline="\n")
    print(f"{len(values)} actual offline events, {len({v['agent'] for v in values})} agents; no real LLM calls")

if __name__=="__main__":asyncio.run(record())
