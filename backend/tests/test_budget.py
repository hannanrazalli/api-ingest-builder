"""Durable, job-scoped approval: no real provider calls or credentials."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.agents.explainer import Explainer
from backend.app.main import create_app
from backend.cost_guard import BudgetExceeded, CostGuard
from backend.fixtures.runtime import FixtureHTTP
from backend.models import Job, Settings
from backend.models.tools import Explanation
from backend.orchestrator.research import ResearchPipeline
from backend.tests.test_research import live_settings, mocked_provider


def test_research_approval_reuses_job_and_keeps_global_limits(store):
    live_settings(store, max_llm_calls=0)
    provider = mocked_provider("coingecko")
    app = create_app(store.path)
    app.state.research_factory = lambda: ResearchPipeline(
        store, fetcher=FixtureHTTP("coingecko"), provider_factory=provider
    )
    with TestClient(app) as client:
        job = client.post("/api/research", json={"url": "coingecko.com", "demo": False}).json()
        # The SSE terminates only once the blocked result is durable.
        assert "event: done" in client.get(f"/api/jobs/{job['id']}/events").text
        blocked = store.job(job["id"])
        assert blocked.status == "waiting" and blocked.calls == 0 and not provider.records
        endpoint = f"/api/jobs/{job['id']}/budget"
        assert client.post(endpoint, json={"approve": True, "max_llm_calls": 0}).status_code == 422
        approved = client.post(endpoint, json={"approve": True}).json()
        assert approved["job"]["id"] == job["id"]
        assert approved["job"]["status"] == "success"
        assert approved["job"]["calls"] == 1 and len(provider.records) == 1
        assert store.settings().max_llm_calls == 0
        assert client.post(endpoint, json={"approve": True}).status_code == 409


def test_explain_can_resume_after_app_restart_and_decline_never_calls(store, monkeypatch):
    store.save_settings(Settings(provider="codex_cli", max_llm_calls=0))
    calls = []

    class Fake:
        def __init__(self, settings, store, guard, bus):
            self.guard = guard

        async def structured(self, *args, **kwargs):
            self.guard.reserve_codex(120)
            calls.append(True)
            return Explanation(language="Malay", summary="Salin data", steps=[], concepts=[])

    original = Explainer.run

    async def fake_run(self, store, request, **kwargs):
        return await original(self, store, request, Fake, **kwargs)

    monkeypatch.setattr(Explainer, "run", fake_run)
    with TestClient(create_app(store.path)) as client:
        response = client.post("/api/explain", json={"text": "df = source.copy()"})
        assert response.status_code == 409
        job_id = response.json()["job"]["id"]
    with TestClient(create_app(store.path)) as client:
        result = client.post(f"/api/jobs/{job_id}/budget", json={"approve": True}).json()
        assert result["result"]["explanation"]["summary"] == "Salin data"
        assert result["job"]["input_tokens"] is None
        assert result["job"]["cost_usd"] is None and len(calls) == 1
        blocked = client.post("/api/explain", json={"text": "df = other.copy()"}).json()["job"]
        denied = client.post(f"/api/jobs/{blocked['id']}/budget", json={"approve": False})
        assert denied.json()["declined"] and len(calls) == 1
        assert store.job(blocked["id"]).status == "error"
        assert "event: done" in client.get(f"/api/jobs/{blocked['id']}/events").text


def test_budget_claim_is_atomic_and_does_not_reset_usage(store):
    job = Job(id="race", status="waiting", calls=2, input_tokens=90, budget_ready=True)
    store.save_job(job)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: store.claim_waiting("race", {"max_llm_calls": 3}), range(2))
        )
    assert sum(value is not None for value in results) == 1
    guard = CostGuard(Settings(max_llm_calls=0), store.job("race"))
    guard.reserve(10, 1)
    assert guard.job.calls == 3 and guard.job.input_tokens == 100
    with pytest.raises(BudgetExceeded):
        guard.reserve(10, 1)


def test_pending_omits_transient_credentials_and_provider_change_blocks_retry(store):
    from backend.models.research import ResearchRequest

    job = Job(id="secret", status="waiting", budget_ready=True)
    store.save_job(job)
    store.save_pending(
        job.id, "research", ResearchRequest(url="example.com", api_key="transient-key")
    )
    assert "transient-key" not in str(store.pending(job.id))
    settings = store.settings()
    settings.provider = "codex_cli"
    store.save_settings(settings)
    with TestClient(create_app(store.path)) as client:
        assert client.post("/api/jobs/secret/budget", json={"approve": True}).status_code == 409
        assert (
            client.post(
                "/api/jobs/secret/budget",
                json={"approve": False},
                headers={"origin": "https://elsewhere.example"},
            ).status_code
            == 403
        )
        assert client.post("/api/jobs/missing/budget", json={"approve": False}).status_code == 404


def test_converter_approval_returns_artifacts_with_cumulative_usage(store, monkeypatch):
    from backend.agents.converter import Converter
    from backend.models.tools import FragmentResult

    store.save_settings(Settings(max_llm_calls=0))

    class Fake:
        def __init__(self, settings, store, guard, bus):
            self.guard = guard

        async def structured(self, *args, **kwargs):
            self.guard.reserve(100, 10)
            return FragmentResult(sql_expression="amount")

    original = Converter.run

    async def fake_run(self, store, request, **kwargs):
        return await original(self, store, request, Fake, **kwargs)

    monkeypatch.setattr(Converter, "run", fake_run)
    with TestClient(create_app(store.path)) as client:
        response = client.post(
            "/api/convert", json={"sql": "select mystery(amount) from source", "allow_llm": True}
        )
        assert response.status_code == 409
        job = response.json()["job"]
        approved = client.post(f"/api/jobs/{job['id']}/budget", json={"approve": True}).json()
        assert approved["job"]["calls"] == 1
        assert approved["job"]["input_tokens"] == 100
        assert "LLM-generated" in approved["result"]["pandas"]
        assert store.settings().max_llm_calls == 0


def test_failed_retry_returns_terminal_job_and_safe_error(store, monkeypatch):
    from backend.llm.errors import ProviderError

    store.save_settings(Settings(provider="codex_cli", max_llm_calls=0))

    class Fake:
        def __init__(self, settings, store, guard, bus):
            self.guard = guard

        async def structured(self, *args, **kwargs):
            self.guard.reserve_codex(10)
            raise ProviderError("private-provider-diagnostic")

    original = Explainer.run

    async def fake_run(self, store, request, **kwargs):
        return await original(self, store, request, Fake, **kwargs)

    monkeypatch.setattr(Explainer, "run", fake_run)
    with TestClient(create_app(store.path)) as client:
        job = client.post("/api/explain", json={"text": "value = 10"}).json()["job"]
        response = client.post(f"/api/jobs/{job['id']}/budget", json={"approve": True})
        assert response.status_code == 422
        assert response.json()["job"]["status"] == "error"
        assert "private-provider-diagnostic" not in response.text
