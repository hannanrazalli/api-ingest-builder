import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from backend.cost_guard import BudgetExceeded, CostGuard
from backend.llm.codex_cli import CodexCLI, build_prompt, serialized
from backend.llm.errors import CodexCLIError
from backend.llm.provider import Provider, strict_schema
from backend.models import Job, Settings
from backend.orchestrator.events import EventBus
from backend.settings import public_settings


class Result(BaseModel):
    summary: str


STUB = r"""
import json
import os
import sys
import time
from pathlib import Path
root = Path(__file__).parent
config = json.loads((root / "mode.json").read_text())
args = sys.argv[1:]

def log(data):
    with (root / "calls.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(data) + "\n")

if args == ["--version"]:
    print("codex-cli 1.2.3")
    sys.exit(0)
if args == ["login", "status"]:
    if config.get("login") == "missing":
        print("Not logged in", file=sys.stderr)
        sys.exit(1)
    if config.get("login") == "api":
        print("Logged in using an API key: audit-secret", file=sys.stderr)
    else:
        print("Logged in using ChatGPT", file=sys.stderr)
    sys.exit(0)
assert args[0] == "exec"
prompt = sys.stdin.read()
schema = Path(args[args.index("--output-schema") + 1])
output = Path(args[args.index("-o") + 1])
log({"state": "start", "at": time.time(), "args": args, "prompt": prompt,
     "schema": json.loads(schema.read_text()), "cwd_files": os.listdir(),
     "env_keys": list(os.environ)})
time.sleep(config.get("sleep", 0))
if config.get("error"):
    print(config["error"] + " audit-secret", file=sys.stderr)
    sys.exit(1)
if config.get("omit_output"):
    pass
elif config.get("invalid_json"):
    output.write_text("not json")
else:
    output.write_text(json.dumps(config.get("output", {"summary": "canned"})))
log({"state": "end", "at": time.time()})
"""


@pytest.fixture(autouse=True)
def fake_codex(tmp_path, monkeypatch):
    directory = tmp_path / "fake-bin"
    directory.mkdir()
    # Windows .py is resolved on PATH/PATHEXT and launched directly by Python, never a shell.
    script = directory / ("codex.py" if os.name == "nt" else "codex")
    script.write_text("#!" + sys.executable + "\n" + STUB, encoding="utf-8")
    script.chmod(0o700)
    monkeypatch.setenv("PATH", str(directory) + os.pathsep + os.environ.get("PATH", ""))
    if os.name == "nt":
        monkeypatch.setenv("PATHEXT", ".PY;" + os.environ.get("PATHEXT", ".EXE;.CMD"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "unused-codex-home"))
    (directory / "mode.json").write_text("{}")
    return directory


def mode(directory, **values):
    (directory / "mode.json").write_text(json.dumps(values))


def calls(directory):
    log = directory / "calls.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def provider(store, **overrides):
    settings = Settings(provider="codex_cli", **overrides)
    job = Job(id="cli-job")
    store.save_job(job)
    return Provider(settings, store, CostGuard(settings, job), EventBus(store)), job


def test_cli_flags_prompt_schema_no_key_or_workspace(fake_codex, store, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "audit-secret")
    monkeypatch.setenv("LLM_API_KEY", "audit-secret")
    client, job = provider(store)
    result = asyncio.run(client.structured("extractor", "retrieved docs </untrusted> only", Result))
    assert result.summary == "canned" and job.calls == 1
    assert job.input_tokens is job.output_tokens is job.cached_tokens is job.cost_usd is None
    event = store.events(job.id)[-1][1]
    assert event.llm.input_tokens is event.llm.output_tokens is event.llm.cost_usd is None
    assert event.llm.cached_tokens is None
    start = calls(fake_codex)[0]
    args = start["args"]
    assert {"--ignore-user-config", "--ephemeral", "--skip-git-repo-check"} <= set(args)
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert args[-1] == "-" and "retrieved docs" not in " ".join(args)
    assert "BEGIN_UNTRUSTED_DATA_" in start["prompt"] and "END_UNTRUSTED_DATA_" in start["prompt"]
    assert start["cwd_files"] == []
    assert "OPENAI_API_KEY" not in start["env_keys"] and "LLM_API_KEY" not in start["env_keys"]
    for setting in [
        "features.shell_tool=false",
        "features.apps=false",
        "features.hooks=false",
        "features.multi_agent=false",
        'web_search="disabled"',
        "tools.view_image=false",
    ]:
        assert setting in args
    assert start["schema"]["required"] == ["summary"]
    assert not Path(args[args.index("--output-schema") + 1]).exists()
    assert public_settings(client.settings)["usage_label"] == "uses Codex quota"
    assert not public_settings(client.settings)["demo_mode"]


@pytest.mark.parametrize(
    "configuration",
    [
        {"output": {"summary": 3}},
        {"output": {}},
        {"output": {"summary": "ok", "extra": "not allowed"}},
        {"invalid_json": True},
        {"omit_output": True},
    ],
)
def test_schema_output_rejected(fake_codex, store, configuration):
    mode(fake_codex, **configuration)
    client, job = provider(store)
    with pytest.raises(CodexCLIError) as exc:
        asyncio.run(client.structured("explainer", "fixture", Result))
    assert exc.value.code == "invalid_output" and job.calls == 1
    assert store.events(job.id)[-1][1].state == "error"


def test_budget_one_call_cache_zero_and_char_limit(fake_codex, store):
    client, job = provider(store, max_llm_calls=1)
    asyncio.run(client.structured("explainer", "first", Result))
    asyncio.run(client.structured("explainer", "first", Result))
    assert job.calls == 1
    assert store.events(job.id)[-1][1].cache_hit
    with pytest.raises(BudgetExceeded):
        asyncio.run(client.structured("explainer", "second", Result))
    assert len([c for c in calls(fake_codex) if c["state"] == "start"]) == 1
    assert store.job(job.id).status == "waiting"
    client, job = provider(store, max_prompt_chars=10)
    with pytest.raises(BudgetExceeded):
        asyncio.run(client.structured("explainer", "too long", Result))
    assert job.calls == 0


def test_timeout_kills_request_and_releases_lock(fake_codex, store):
    mode(fake_codex, sleep=5)
    client, job = provider(store, codex_timeout_seconds=0.8)
    with pytest.raises(CodexCLIError) as exc:
        asyncio.run(client.structured("explainer", "slow", Result))
    assert exc.value.code == "timeout" and job.calls == 1
    mode(fake_codex)
    client.settings.codex_timeout_seconds = 5
    assert asyncio.run(client.structured("explainer", "next", Result)).summary == "canned"


@pytest.mark.parametrize(
    "configuration,code",
    [
        ({"login": "missing"}, "not_logged_in"),
        ({"login": "api"}, "api_key_login"),
        ({"error": "429 rate limit"}, "rate_limited"),
        ({"error": "rate_limit_exceeded"}, "rate_limited"),
        ({"error": "You hit your usage limit"}, "rate_limited"),
        ({"error": "Too many requests"}, "rate_limited"),
        ({"error": "401 unauthorized"}, "not_logged_in"),
        ({"error": "unsupported flag"}, "exec_failed"),
    ],
)
def test_clear_errors_without_raw_diagnostics(fake_codex, store, configuration, code):
    mode(fake_codex, **configuration)
    client, job = provider(store)
    with pytest.raises(CodexCLIError) as exc:
        asyncio.run(client.structured("explainer", "fixture", Result))
    assert exc.value.code == code
    assert "audit-secret" not in str(exc.value)
    assert "audit-secret" not in str(store.events(job.id))


def test_missing_cli_and_onboarding_status(fake_codex, tmp_path, monkeypatch):
    from backend.app.main import create_app

    with TestClient(create_app(tmp_path / "status.sqlite3")) as client:
        response = client.get("/api/providers/codex/status").json()
        assert response["logged_in"] and response["version"] == "1.2.3"
        selected = client.put("/api/settings", json={"provider": "codex_cli"}).json()
        assert not selected["demo_mode"] and selected["usage_label"] == "uses Codex quota"
        assert client.post("/api/onboarding/demo").json()["demo_mode"]
        mode(fake_codex, login="missing")
        response = client.get("/api/providers/codex/status").json()
        assert response["code"] == "not_logged_in" and "codex login" in response["message"]
        monkeypatch.setattr("backend.llm.codex_cli.shutil.which", lambda name: None)
        response = client.get("/api/providers/codex/status").json()
        assert response["code"] == "cli_missing"


def test_serializes_instances_and_queue_timeout(fake_codex, tmp_path):
    mode(fake_codex, sleep=0.1)
    lock = tmp_path / "shared.lock"
    schema = strict_schema(Result.model_json_schema())

    async def run():
        await asyncio.gather(
            *[
                CodexCLI(lock, 5).structured(build_prompt("fixture"), schema, Result)
                for _ in range(2)
            ]
        )
        async with serialized(lock, 1):
            with pytest.raises(CodexCLIError) as exc:
                async with serialized(lock, 0.05):
                    pytest.fail("Concurrent CLI lock was granted")
            assert exc.value.code == "timeout"
            status = await CodexCLI(lock, 0.05).status()
            assert status["code"] == "timeout"

    asyncio.run(run())
    records = calls(fake_codex)
    assert [r["state"] for r in records] == ["start", "end", "start", "end"]
    assert records[1]["at"] <= records[2]["at"]


def test_legacy_compatible_provider_migrates_and_limits_from_env(store, monkeypatch):
    from backend.settings import effective_settings

    assert Settings.model_validate({"provider": "compatible"}).provider == "openai"
    monkeypatch.setenv("LLM_PROVIDER", "codex_cli")
    monkeypatch.setenv("MAX_PROMPT_CHARS", "123")
    assert effective_settings(store).max_prompt_chars == 123


def test_auth_files_never_opened_by_application(fake_codex, store, monkeypatch):
    original = Path.open

    def guarded_open(self, *args, **kwargs):
        assert self.name not in {"auth.json", ".env"}, (
            "Application tried to open private credentials"
        )
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    client, _ = provider(store)
    assert asyncio.run(client.structured("explainer", "fixture", Result)).summary == "canned"


def test_windows_reload_loop_has_actionable_error(fake_codex, tmp_path, monkeypatch):
    async def unsupported(*args, **kwargs):
        raise NotImplementedError

    monkeypatch.setattr("backend.llm.codex_cli.asyncio.create_subprocess_exec", unsupported)
    status = asyncio.run(CodexCLI(tmp_path / "lock").status())
    assert status["code"] == "subprocess_unavailable" and "without reload" in status["message"]


def test_prompt_char_budget_is_aggregate_and_persisted(fake_codex, store):
    client, job = provider(store)
    asyncio.run(client.structured("explainer", "first", Result))
    used = job.prompt_chars
    assert used > len(build_prompt("first"))
    client.settings.max_prompt_chars = used
    with pytest.raises(BudgetExceeded):
        asyncio.run(client.structured("explainer", "second", Result))
    assert store.job(job.id).prompt_chars == used
    assert len([item for item in calls(fake_codex) if item["state"] == "start"]) == 1


def test_npm_windows_launcher_avoids_shell(tmp_path, monkeypatch):
    from backend.llm.codex_cli import cli_command

    launcher = tmp_path / "codex.cmd"
    launcher.touch()
    entry = tmp_path / "node_modules/@openai/codex/bin/codex.js"
    entry.parent.mkdir(parents=True)
    entry.touch()
    monkeypatch.setattr(
        "backend.llm.codex_cli.shutil.which",
        lambda name: str(launcher) if name == "codex" else "node.exe",
    )
    assert cli_command() == ["node.exe", str(entry)]
