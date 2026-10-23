import asyncio
import json

import httpx
import pytest

from backend.agents.base import AgentContext
from backend.agents.fetcher import DocClient, Fetcher, FetchError
from backend.agents.prober import parse_openapi
from backend.fixtures.runtime import ROOT, FixtureHTTP
from backend.llm.provider import Provider
from backend.models import Job, Settings
from backend.models.research import ResearchRequest
from backend.orchestrator.events import EventBus
from backend.orchestrator.research import ResearchPipeline


def mocked_provider(name, replies=None):
    records = []

    def factory(settings, store, guard, bus):
        def respond(request):
            records.append(json.loads(request.content))
            value = (
                replies.pop(0)
                if replies
                else json.loads((ROOT / name / "extraction.json").read_text())
            )
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": json.dumps(value)}}],
                    "usage": {"prompt_tokens": 500, "completion_tokens": 150},
                },
            )

        return Provider(settings, store, guard, bus, httpx.MockTransport(respond))

    factory.records = records
    return factory


def live_settings(store, **kwargs):
    store.save_settings(
        Settings(
            api_key="fixture-provider-key",
            model_fast="fixture-fast",
            model_smart="fixture-smart",
            **kwargs,
        )
    )


def run(
    store, name="frankfurter", *, openapi=True, failures=0, not_found=False, force=False, **request
):
    live_settings(store)
    http = FixtureHTTP(name, openapi=openapi, failures=failures, not_found=not_found)
    provider = mocked_provider(name)
    pipeline = ResearchPipeline(store, fetcher=http, provider_factory=provider)
    url = "https://frankfurter.dev/" if name == "frankfurter" else "https://www.coingecko.com/"
    result = asyncio.run(pipeline.run(ResearchRequest(url=url, demo=False, force=force, **request)))
    return result, http, provider


def test_openapi_zero_calls_and_cache_zero_network(store):
    result, http, provider = run(store)
    assert result.status == "ready" and result.job.calls == 0 and not provider.records
    assert result.spec.endpoints[0].verified and result.profile.date_fields == ["date"]
    repeated, http, provider = run(store)
    assert repeated.cache_hit and repeated.job.calls == 0 and not provider.records
    assert not http.requests or all("rates" in url for url, _ in http.requests)
    assert result.spec.endpoints[0].source_url


def test_normal_one_call_and_cg_auth_host_bound(store):
    result, http, provider = run(
        store, "coingecko", api_key="fixture-target-key", api_key_host="api.coingecko.com"
    )
    assert result.status == "ready", result.warnings
    assert result.job.calls == len(provider.records) == 1
    assert result.spec.auth.header_name == "x-cg-demo-api-key"
    assert result.spec.endpoints[0].date_params.format == "unix"
    verify = [(url, args) for url, args in http.requests if "market_chart/range" in url]
    assert len(verify) == 1 and verify[0][1]["headers"]["x-cg-demo-api-key"] == "fixture-target-key"
    assert not any(
        "fixture-target-key" in event.model_dump_json() for _, event in store.events(result.job.id)
    )


def test_repair_bounded_three_calls_fast_then_smart(store):
    result, http, provider = run(
        store,
        "coingecko",
        failures=2,
        api_key="fixture-target-key",
        api_key_host="api.coingecko.com",
    )
    assert result.status == "ready", result.warnings
    assert result.job.calls == len(provider.records) == 3
    assert [body["model"] for body in provider.records] == [
        "fixture-smart",
        "fixture-fast",
        "fixture-smart",
    ]
    events = [e for _, e in store.events(result.job.id)]
    for agent in {
        "orchestrator",
        "prober",
        "fetcher",
        "retriever",
        "extractor",
        "verifier",
        "repair",
        "profiler",
    }:
        states = {e.state for e in events if e.agent == agent}
        assert {"walking", "working", "success"} <= states
    assert any(e.state == "error" and e.agent == "verifier" for e in events)


def test_no_auth_no_repair_or_llm_guessing(store):
    result, _, provider = run(store, "coingecko")
    assert result.status == "unverified" and result.job.calls == 1
    assert len(provider.records) == 1
    result, _, provider = run(store, not_found=True, force=True)
    assert result.status == "not_found" and result.spec is None and not provider.records


def test_budget_blocks_pipeline_before_llm(store):
    live_settings(store, max_llm_calls=0)
    factory = mocked_provider("coingecko")
    result = asyncio.run(
        ResearchPipeline(store, fetcher=FixtureHTTP("coingecko"), provider_factory=factory).run(
            ResearchRequest(url="coingecko.com", demo=False)
        )
    )
    assert result.status == "budget_blocked" and result.job.calls == 0 and not factory.records
    assert result.job.status == "waiting"


def test_demo_zero_calls_and_not_live_verified(store):
    result = asyncio.run(ResearchPipeline(store).run(ResearchRequest(url="coingecko.com")))
    assert result.demo and result.status == "ready" and result.job.calls == 0
    assert not result.spec.endpoints[0].verified
    assert result.profile.nested


def test_swagger_local_ref_and_unsupported_security():
    doc = {
        "swagger": "2.0",
        "info": {"title": "Example"},
        "host": "api.example.com",
        "basePath": "/v1",
        "securityDefinitions": {"oauth": {"type": "oauth2"}},
        "security": [{"oauth": []}],
        "parameters": {
            "date": {"name": "date", "in": "query", "type": "string", "description": "ISO date"}
        },
        "paths": {"/rates": {"get": {"parameters": [{"$ref": "#/parameters/date"}]}}},
    }
    spec, _ = parse_openapi(json.dumps(doc).encode(), "https://example.com/swagger.json")
    assert str(spec.base_url) == "https://api.example.com/v1"
    assert spec.auth.type == "unsupported" and spec.unsupported_reason
    assert spec.endpoints[0].date_params.format == "iso"
    yaml = (
        b"openapi: 3.0.0\ninfo: {title: test}\n"
        b"servers: [{url: https://example.com}]\npaths: {/rates: {get: {}}}"
    )
    assert parse_openapi(yaml, "https://example.com/openapi.yaml")[0]


def test_robots_disallow_and_fetch_dedupe(store):
    class Blocked(FixtureHTTP):
        async def get(self, url, **kwargs):
            if url.endswith("robots.txt"):
                return b"User-agent: *\nDisallow: /docs"
            return b"<nav>noise</nav><main>REST API GET /rates</main><footer>noise</footer>"

    client = DocClient(Blocked("frankfurter"), delay=0)
    with pytest.raises(FetchError):
        asyncio.run(client.raw("https://example.com/docs"))
    job = Job(id="clean")
    store.save_job(job)
    ctx = AgentContext(store, job, EventBus(store))
    pages = [
        ("https://example.com/a", b"<nav>noise</nav><main>API GET /rates</main>"),
        ("https://example.com/b", b"<main>API GET /rates</main>"),
    ]
    docs, _ = asyncio.run(Fetcher().run(ctx, client, pages))
    assert len(docs) == 1 and "noise" not in docs[0].markdown


def test_extractor_rejects_invented_sources(store):
    live_settings(store)
    value = json.loads((ROOT / "coingecko/extraction.json").read_text())
    value["endpoints"][0]["source_url"] = "https://invented.example/docs"
    factory = mocked_provider("coingecko", [value])
    result = asyncio.run(
        ResearchPipeline(store, fetcher=FixtureHTTP("coingecko"), provider_factory=factory).run(
            ResearchRequest(url="coingecko.com", demo=False)
        )
    )
    assert result.status == "error" and result.spec is None


def test_recorded_demo_logs_contract():
    from backend.models import Event

    files = list((ROOT / "demo_events").glob("*.json"))
    assert len(files) >= 6
    for file in files:
        events = [Event.model_validate(event) for event in json.loads(file.read_text())]
        assert events and events[-1].agent == "orchestrator"
        assert not any("fixture-target-key" in e.model_dump_json() for e in events)


def test_js_docs_degrade_with_clear_warning(store, monkeypatch):
    from backend.agents.fetcher import JSRenderer

    monkeypatch.setattr("backend.agents.fetcher.importlib.util.find_spec", lambda name: None)
    with pytest.raises(FetchError, match="optional Playwright"):
        asyncio.run(JSRenderer().render("https://example.com", None))


def test_api_runs_demo_job_without_network(tmp_path):
    import time

    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    with TestClient(create_app(tmp_path / "api.sqlite3")) as client:
        job = client.post("/api/research", json={"url": "frankfurter.dev"}).json()
        for _ in range(50):
            result = client.get(f"/api/research/{job['id']}").json()
            if result["status"] != "running":
                break
            time.sleep(0.01)
        assert result["status"] == "ready" and result["demo"]
        assert client.get("/api/jobs").json()[0]["result"]["spec"]


def test_wire_schema_preserves_default_field_and_removes_only_annotations():
    from backend.llm.provider import strict_schema
    from backend.models.research import Extraction

    schema = strict_schema(Extraction.model_json_schema())
    param = schema["$defs"]["WireParam"]
    assert "default" in param["properties"] and "default" in param["required"]
    assert "default" not in param["properties"]["default"]
