import asyncio
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from backend.agents.base import AgentContext
from backend.agents.generator import Generator
from backend.agents.profiler import Profiler
from backend.fixtures.runtime import load_fixture
from backend.models import Job, Pagination
from backend.models.generation import GenerationOptions
from backend.orchestrator.events import EventBus

GOLDENS = Path(__file__).parent / "golden" / "generator"
MODES = ["snippet", "daily", "backfill", "chunking", "ndjson", "full_ingestion"]


def prepare(store, fixture="coingecko"):
    spec, sample = load_fixture(fixture)
    job = Job(id="generation")
    store.save_job(job)
    ctx = AgentContext(store, job, EventBus(store))
    profile = asyncio.run(Profiler().run(ctx, sample))
    return spec, sample, ctx, profile


@pytest.mark.parametrize("fixture", ["coingecko", "frankfurter"])
@pytest.mark.parametrize("mode", MODES)
def test_goldens_syntax_lint_and_idempotency(store, fixture, mode, tmp_path):
    spec, _, ctx, profile = prepare(store, fixture)
    options = GenerationOptions(mode=mode)
    first = asyncio.run(Generator().run(ctx, spec, options, profile))
    assert first == Generator().render(spec, options, profile)
    assert first == (GOLDENS / f"{fixture}_{mode}.py").read_text(encoding="utf-8")
    output = tmp_path / "output.py"
    output.write_text(first, encoding="utf-8")
    subprocess.run(
        [sys.executable, "-m", "py_compile", str(output)], check=True, capture_output=True
    )
    lint = subprocess.run(
        [sys.executable, "-m", "ruff", "check", str(output)], capture_output=True, text=True
    )
    assert lint.returncode == 0, lint.stdout
    assert ctx.job.calls == 0
    assert store.events(ctx.job.id)[-1][1].agent == "generator"


def test_runtime_retry_dates_and_atomic_partition_idempotency(store, monkeypatch, tmp_path):
    spec, sample, _, profile = prepare(store)
    code = Generator().render(spec, GenerationOptions(mode="backfill"), profile)
    namespace = {"__name__": "generated_test"}
    exec(compile(code, "generated.py", "exec"), namespace)
    monkeypatch.setenv("COINGECKO_API_KEY", "fixture-target")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(namespace["time"], "sleep", lambda _: None)
    retry = Mock(status_code=429, headers={"Retry-After": "0"})
    ok = Mock(status_code=200, headers={}, links={})
    ok.json.return_value = sample
    get = Mock(side_effect=[retry, ok, ok])
    monkeypatch.setattr(namespace["requests"], "get", get)
    namespace["coingecko"]("2026-01-01")
    files = list(tmp_path.rglob("*.ndjson"))
    assert len(files) == 1
    before = files[0].read_text()
    namespace["coingecko"]("2026-01-01")
    assert files[0].read_text() == before
    args = get.call_args.kwargs
    assert args["params"]["to"] - args["params"]["from"] == 86399
    assert args["headers"]["x-cg-demo-api-key"] == "fixture-target"
    assert args["allow_redirects"] is False
    assert "fixture-target" not in code


def test_chunk_windows_and_pagination(store, monkeypatch):
    spec, _, _, profile = prepare(store, "frankfurter")
    spec.endpoints[0].max_range_days = 2
    spec.endpoints[0].pagination = Pagination(type="page", param="page")
    code = Generator().render(spec, GenerationOptions(mode="chunking", chunk_days=5), profile)
    assert "chunk_days=2" in code
    namespace = {"__name__": "test"}
    exec(code, namespace)
    monkeypatch.setattr(namespace["time"], "sleep", lambda _: None)
    responses = []
    for payload in [[{"id": 1}], []]:
        response = Mock(status_code=200, headers={}, links={})
        response.json.return_value = payload
        responses.append(response)
    get = Mock(side_effect=responses)
    monkeypatch.setattr(namespace["requests"], "get", get)
    assert namespace["fetch_records"]("2026-01-01", "2026-01-02") == [{"id": 1}]
    assert get.call_count == 2


def test_no_eval_injection_or_unsupported_auth(store):
    spec, _, _, profile = prepare(store)
    value = "x'); __import__('os').system('NEVER_EXECUTE'); #"
    code = Generator().render(spec, GenerationOptions(params={"id": value}), profile)
    assert "__import__" not in code or repr(value) in code or "%27" in code
    compile(code, "safe.py", "exec")
    spec.auth.type = "unsupported"
    with pytest.raises(ValueError):
        Generator().render(spec, GenerationOptions(), profile)


def test_cursor_not_guessed_and_flatten_is_profile_gated(store):
    spec, _, _, profile = prepare(store, "frankfurter")
    with pytest.raises(ValueError, match="nested"):
        Generator().render(spec, GenerationOptions(flatten=True), profile)
    spec.endpoints[0].pagination = Pagination(type="cursor", param="cursor")
    with pytest.raises(ValueError, match="cursor path"):
        Generator().render(spec, GenerationOptions(), profile)


def test_full_ingestion_s3_contract_without_airflow_network(store, monkeypatch):
    import types

    spec, sample, _, profile = prepare(store, "frankfurter")
    hook = Mock()
    for name in [
        "airflow",
        "airflow.providers",
        "airflow.providers.amazon",
        "airflow.providers.amazon.aws",
        "airflow.providers.amazon.aws.hooks",
        "airflow.providers.amazon.aws.hooks.s3",
        "dotenv",
    ]:
        module = types.ModuleType(name)
        module.__path__ = []
        module.S3Hook = Mock(return_value=hook)
        module.load_dotenv = Mock()
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setenv("BUCKET_NAME", "fixture-bucket")
    code = Generator().render(spec, GenerationOptions(mode="full_ingestion"), profile)
    namespace = {"__name__": "test"}
    exec(code, namespace)
    monkeypatch.setattr(namespace["time"], "sleep", lambda _: None)
    response = Mock(status_code=200, headers={})
    response.json.return_value = sample
    monkeypatch.setattr(namespace["requests"], "get", Mock(return_value=response))
    namespace["frankfurter"]("2026-01-01")
    call = hook.load_string.call_args.kwargs
    assert call["replace"] is True and call["bucket_name"] == "fixture-bucket"
    assert call["key"] == "raw/frankfurter/year=2026/month=01/day=01/frankfurter_20260101.ndjson"
    assert len(call["string_data"].splitlines()) == 3


def test_inclusive_chunk_windows_and_offset_host_protection(store, monkeypatch):
    spec, _, _, profile = prepare(store, "frankfurter")
    namespace = {"__name__": "test"}
    exec(Generator().render(spec, GenerationOptions(mode="chunking"), profile), namespace)
    windows = []
    namespace["frankfurter"] = lambda ds, end: windows.append((ds, end))
    namespace["backfill"]("2026-01-01", "2026-01-05", 2)
    assert windows == [
        ("2026-01-01", "2026-01-02"),
        ("2026-01-03", "2026-01-04"),
        ("2026-01-05", "2026-01-05"),
    ]
    with pytest.raises(ValueError, match="host"):
        namespace["_get"]("https://other.example/steal", {}, {})


def test_sample_preview_is_bounded_and_matches_dotted_flattening():
    from backend.agents.generator import sample_preview

    rows = [{"nested": {"a": 1}, "values": [2, 3]}] * 5
    preview = sample_preview({"data": rows}, "data")
    assert len(preview.splitlines()) == 3
    assert json.loads(preview.splitlines()[0]) == {"nested.a": 1, "values.0": 2, "values.1": 3}
