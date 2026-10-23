import asyncio
import json
from pathlib import Path

import pandas as pd
import pytest

from backend.agents.converter import Converter
from backend.agents.explainer import Explainer, detect_language
from backend.converter import pandas_emitter, pyspark_emitter
from backend.converter.compiler import Unsupported, parse, plan
from backend.converter.pandas_runtime import _query
from backend.converter.verify_worker import compare
from backend.models.tools import ConvertRequest, ExplainRequest, Explanation, FragmentResult

ROOT = Path(__file__).parents[1]
CASES = json.loads((ROOT / "fixtures/sql/cases.json").read_text())
TABLES = {
    "source": [
        {"id": 1, "category": "a", "amount": 10},
        {"id": 2, "category": "a", "amount": 20},
        {"id": 3, "category": "b", "amount": 20},
        {"id": 4, "category": "b", "amount": None},
    ],
    "other": [{"id": 2, "label": "two"}, {"id": 5, "label": "five"}],
}


@pytest.mark.parametrize("case", CASES, ids=[i["name"] for i in CASES])
def test_golden_and_semantics(case):
    node = parse(case["sql"])
    for target, emitter in [("pandas", pandas_emitter), ("pyspark", pyspark_emitter)]:
        code = emitter.emit(node)
        assert code == (
            ROOT / "tests/golden/sql" / (case["name"] + "." + target + ".py")
        ).read_text(encoding="utf-8")
        compile(code, "generated.py", "exec")
    result = compare(case["sql"], "spark", plan(node), TABLES)
    assert result["match"], case["name"]
    # The generated pandas artifact must execute independently of this package.
    namespace = {name: pd.DataFrame(rows) for name, rows in TABLES.items()}
    exec(pandas_emitter.emit(node), namespace)
    pd.testing.assert_frame_equal(
        namespace["df"], _query(plan(node), {n: pd.DataFrame(r) for n, r in TABLES.items()})
    )


@pytest.mark.parametrize(
    "sql",
    [
        "delete from source",
        "select * from read_csv('private')",
        "select * from source; select 1",
        "select * from information_schema.tables",
    ],
)
def test_read_only_inputs(sql):
    with pytest.raises((ValueError, Unsupported)):
        plan(parse(sql))


def test_zero_calls_and_cache(store):
    value = asyncio.run(Converter().run(store, ConvertRequest(sql="select * from source")))
    repeat = asyncio.run(Converter().run(store, ConvertRequest(sql="select * from source")))
    assert value["job"]["calls"] == repeat["job"]["calls"] == 0
    assert repeat["cache_hit"]


def test_fragment_fallback_only_and_cache(store):
    seen = []

    class Fake:
        def __init__(self, settings, store, guard, bus):
            self.guard = guard

        async def structured(self, purpose, text, result_type, **kwargs):
            seen.append(json.loads(text))
            self.guard.reserve(100, 100)
            return FragmentResult(sql_expression="amount + 1")

    request = ConvertRequest(sql="select custom_increment(amount) as n from source", allow_llm=True)
    result = asyncio.run(Converter().run(store, request, Fake))
    assert result["job"]["calls"] == 1 and result["llm_generated"]
    assert "source" not in seen[0]["fragment"]
    assert asyncio.run(Converter().run(store, request, Fake))["cache_hit"]
    assert len(seen) == 1


def test_explain_demo_and_cached_live_mock(store):
    assert detect_language("select * from source") == "SQL"
    assert detect_language("df = spark.table('x')") == "PySpark"
    request = ExplainRequest(text="select * from source")
    assert asyncio.run(Explainer().run(store, request))["explanation"]["language"] == "Malay"
    assert asyncio.run(Explainer().run(store, request))["cache_hit"]
    value = store.settings()
    value.provider = "codex_cli"
    store.save_settings(value)

    class Fake:
        def __init__(self, settings, store, guard, bus):
            self.guard = guard

        async def structured(self, purpose, text, result_type, **kwargs):
            self.guard.reserve_codex(len(text))
            return Explanation(
                language="English", summary="A copy", steps=["Copy source"], concepts=["DataFrame"]
            )

    request = ExplainRequest(text="df = other.copy()", language="English")
    assert asyncio.run(Explainer().run(store, request, Fake))["job"]["calls"] == 1
    assert asyncio.run(Explainer().run(store, request, Fake))["job"]["calls"] == 0


def test_converter_budget_guard_and_persisted_events(store):
    from backend.cost_guard import BudgetExceeded

    value = store.settings()
    value.max_llm_calls = 0
    store.save_settings(value)

    class Fake:
        def __init__(self, settings, store, guard, bus):
            self.guard = guard

        async def structured(self, *args, **kwargs):
            self.guard.reserve(1, 1)

    with pytest.raises(BudgetExceeded):
        asyncio.run(
            Converter().run(
                store,
                ConvertRequest(sql="select mystery(amount) from source", allow_llm=True),
                Fake,
            )
        )
    job = store.jobs()[0]
    assert job.calls == 0 and job.status == "waiting"
    assert any(event.state == "waiting" for _, event in store.events(job.id))


def test_tools_api_and_bounded_verify(store):
    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    with TestClient(create_app(store.path)) as client:
        value = client.post("/api/convert", json={"sql": "select * from source"}).json()
        assert value["status"] == "success" and value["job"]["calls"] == 0
        assert client.get("/api/jobs/" + value["job"]["id"]).json()["status"] == "success"
        assert client.post(
            "/api/convert/verify", json={"sql": "select * from source", "tables": TABLES}
        ).json()["match"]
        assert (
            client.post(
                "/api/convert/verify",
                json={"sql": "select * from source", "tables": {"source": TABLES["source"] * 30}},
            ).status_code
            == 422
        )
        explanation = client.post("/api/explain", json={"text": "select * from source"}).json()
        assert explanation["explanation"]["language"] == "Malay"
