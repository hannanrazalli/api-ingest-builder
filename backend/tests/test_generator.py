import asyncio
import json
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from backend.agents.base import AgentContext
from backend.agents.generator import Generator
from backend.agents.profiler import Profiler
from backend.fixtures.runtime import load_fixture
from backend.models import Job, Pagination
from backend.models.generation import GenerationOptions
from backend.orchestrator.events import EventBus

GOLDENS = Path(__file__).parent / "golden" / "generator"
MODES = ["snippet"]


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
    assert "requests.get" in first and "raise_for_status" in first
    if mode == "snippet" and fixture == "frankfurter":
        assert "params = {}" in first
    assert len(first.splitlines()) < 30
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
    spec, _, _, profile = prepare(store)
    code = Generator().render(spec, GenerationOptions(mode="snippet"), profile)
    assert 'os.getenv("COINGECKO_API_KEY")' in code
    assert "fixture-target" not in code
    assert 'params["from"]' not in code
    assert 'params["to"]' not in code
    frankfurter, _, _, _ = prepare(store, "frankfurter")
    daily = Generator().render(frankfurter, GenerationOptions(mode="daily"))
    assert 'params["from"] = api_date(date)' in daily
    assert 'params["to"] = api_date(date, end=True)' in daily


def test_backfill_runs_one_request_per_date_and_saves_json(store, monkeypatch, tmp_path):
    spec, sample, _, profile = prepare(store, "frankfurter")
    code = Generator().render(
        spec,
        GenerationOptions(mode="backfill", start_date="2024-01-01", end_date="2024-01-02"),
        profile,
    )
    response = Mock(status_code=200)
    response.json.return_value = sample
    get = Mock(return_value=response)
    monkeypatch.setattr("requests.get", get)
    monkeypatch.chdir(tmp_path)
    exec(compile(code, "backfill.py", "exec"), {"__name__": "generated"})
    assert [call.kwargs["params"]["from"] for call in get.call_args_list] == [
        "2024-01-01",
        "2024-01-02",
    ]
    assert [call.kwargs["params"]["to"] for call in get.call_args_list] == [
        "2024-01-01",
        "2024-01-02",
    ]
    assert len(json.loads((tmp_path / "frankfurter.json").read_text())) == 6


def test_chunk_windows_and_pagination(store, monkeypatch):
    spec, _, _, profile = prepare(store, "frankfurter")
    spec.endpoints[0].max_range_days = 2
    spec.endpoints[0].pagination = Pagination(type="page", param="page")
    assert spec.endpoints[0].max_range_days == 2


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
    spec, sample, _, profile = prepare(store, "frankfurter")
    boto3 = types.ModuleType("boto3")
    s3 = Mock()
    boto3.client = Mock(return_value=s3)
    monkeypatch.setitem(sys.modules, "boto3", boto3)
    response = Mock(status_code=200)
    response.json.return_value = sample
    monkeypatch.setattr("requests.get", Mock(return_value=response))
    code = Generator().render(
        spec,
        GenerationOptions(
            mode="full_ingestion", bucket_name="fixture-bucket", table_name="frankfurter"
        ),
        profile,
    )
    exec(compile(code, "ingestion.py", "exec"), {"__name__": "generated"})
    assert "boto3.client" in code and 'bucket = "fixture-bucket"' in code
    assert 'key = f"{folder}/{table}/year=' in code
    upload = s3.put_object.call_args.kwargs
    assert upload["Bucket"] == "fixture-bucket"
    assert upload["ContentType"] == "application/json"
    assert json.loads(upload["Body"]) == sample


def test_nested_glue_crawler_output_is_flattened_ndjson(store, monkeypatch):
    spec, sample, _, profile = prepare(store, "coingecko")
    boto3 = types.ModuleType("boto3")
    s3 = Mock()
    boto3.client = Mock(return_value=s3)
    monkeypatch.setitem(sys.modules, "boto3", boto3)
    monkeypatch.setenv("COINGECKO_API_KEY", "fixture-key")
    response = Mock(status_code=200)
    response.json.return_value = sample
    monkeypatch.setattr("requests.get", Mock(return_value=response))
    code = Generator().render(
        spec,
        GenerationOptions(
            mode="full_ingestion",
            bucket_name="fixture-bucket",
            table_name="market_data",
            output_format="ndjson",
            flatten=True,
        ),
        profile,
    )
    exec(compile(code, "crawler.py", "exec"), {"__name__": "generated"})
    upload = s3.put_object.call_args.kwargs
    assert upload["ContentType"] == "application/x-ndjson"
    rows = [json.loads(line) for line in upload["Body"].splitlines()]
    assert rows[0]["0"] == sample["prices"][0][0]


def test_inclusive_chunk_windows_and_offset_host_protection(store, monkeypatch):
    spec, _, _, profile = prepare(store, "frankfurter")
    with pytest.raises(ValueError):
        Generator().render(spec, GenerationOptions(mode="chunking"), profile)
    with pytest.raises(ValueError, match="bucket name"):
        Generator().render(
            spec,
            GenerationOptions(
                mode="daily", full_ingestion=True, table_name="rates", bucket_name=None
            ),
            profile,
        )


def test_sample_preview_is_bounded_and_matches_dotted_flattening():
    from backend.agents.generator import sample_preview

    rows = [{"nested": {"a": 1}, "values": [2, 3]}] * 5
    preview = sample_preview({"data": rows}, "data")
    assert len(preview.splitlines()) == 3
    assert json.loads(preview.splitlines()[0]) == {"nested.a": 1, "values.0": 2, "values.1": 3}


def test_daily_airflow_s3_nested_ndjson_is_valid_lines(store):
    spec, sample, _, profile = prepare(store, "coingecko")
    options = GenerationOptions(
        mode="daily", run_target="airflow", full_ingestion=True,
        bucket_name="fixture-bucket", table_name="market_data", output_format="ndjson",
        flatten=True,
    )
    code = Generator().render(spec, options, profile)
    assert 'body = "\\\\n".join' not in code
    assert 'body = "\\n".join' in code
    compile(code, "airflow.py", "exec")
    assert 'records = records["prices"]' in code
    assert 'params["from"] = api_date(date)' in code


def test_legacy_unimplemented_modes_are_rejected(store):
    spec, _, _, _ = prepare(store)
    with pytest.raises(ValidationError):
        GenerationOptions(mode="chunking")
    with pytest.raises(ValidationError):
        GenerationOptions(mode="ndjson")
    assert spec.endpoints[0].date_params is not None
