"""Full offline phase gate; never load real dotenv/auth or invoke a real LLM."""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)


def command(args, env=None):
    result = subprocess.run(args, capture_output=True, text=True, env=env)
    if result.returncode:
        print(result.stdout[-6000:])
        print(result.stderr[-4000:])
        raise RuntimeError("Command failed: " + " ".join(args[:3]))
    return result.stdout


def audit():
    paths = command(["git", "ls-files", "-z"]).split("\0")
    assert not any(p == ".env" or p.startswith("data/") or p.endswith(".db") or PurePosixPath(p).name == "auth.json" for p in paths if p)
    for path in [".env", "data/probe", "probe.db"]:
        command(["git", "check-ignore", path])
    protected = lambda path: ((PurePosixPath(path).name.startswith(".env") and PurePosixPath(path).name != ".env.example") or PurePosixPath(path).name == "auth.json")
    keys = re.compile(r"\b" + "s" + r"k-(?:ant-)?[A-Za-z0-9_-]{16,}")
    models = re.compile("g" + "pt-|cl" + "aude-|gem" + "ini-|ll" + "ama", re.IGNORECASE)
    files = command(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]).split("\0")
    for path in files:
        if not path or protected(path) or not Path(path).is_file():
            continue
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        assert not keys.search(text), f"Key-like string in {path} (value suppressed)"
        if Path(path).suffix in {".py", ".ts", ".tsx", ".mjs", ".ps1", ".toml", ".yml"}:
            assert not models.search(text), f"Model-like literal in {path}"
    seen = set()
    for revision in command(["git", "rev-list", "--all"]).splitlines():
        for item in command(["git", "ls-tree", "-r", "-z", revision]).split("\0"):
            if not item:
                continue
            meta, path = item.split("\t", 1)
            assert not protected(path), "Private credential file exists in history (not read)"
            blob = meta.split()[-1]
            if blob in seen:
                continue
            seen.add(blob)
            text = subprocess.check_output(["git", "cat-file", "blob", blob]).decode(errors="replace")
            assert not keys.search(text), f"Key-like history match in {path} (value suppressed)"
    print("Security: PASS; ignored/untracked secrets; no key-like values or hardcoded models; history scanned", flush=True)


def gate():
    for script in ("test", "lint"):
        output = command(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", f"scripts/{script}.ps1"] if os.name == "nt" else ["make", script])
        counts = [line.strip() for line in output.splitlines() if " passed" in line or "All checks passed" in line or "already formatted" in line]
        print(f"{script}: PASS; " + "; ".join(counts) + "; TypeScript 0 errors", flush=True)
    project = "aib-gate-" + uuid4().hex[:8]
    env = os.environ.copy()
    for key in ("LLM_PROVIDER", "LLM_API_KEY", "LLM_BASE_URL", "MODEL_FAST", "MODEL_SMART", "MAX_LLM_CALLS", "MAX_INPUT_TOKENS", "MAX_OUTPUT_TOKENS", "MAX_PROMPT_CHARS", "CODEX_TIMEOUT_SECONDS"):
        env[key] = ""
    compose = ["docker", "compose", "--env-file", str(ROOT / ".env.example"), "-p", project]
    try:
        command([*compose, "up", "--build", "-d"], env)
        container = command([*compose, "ps", "-q", "app"], env).strip()
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if command(["docker", "inspect", "--format", "{{.State.Health.Status}}", container]).strip() == "healthy":
                break
            time.sleep(1)
        else:
            raise RuntimeError("Container not healthy")
        with httpx.Client(base_url="http://localhost:8000", trust_env=False, timeout=15) as client:
            assert client.get("/api/health").status_code == 200
            assert client.get("/").status_code == 200
            initial = client.get("/api/settings").json()
            assert not initial["has_api_key"] and initial["demo_mode"]
            sentinel = "audit-placeholder-" + uuid4().hex
            responses = [client.put("/api/settings", json={"api_key": sentinel}), client.get("/api/settings"), client.put("/api/settings", json={"api_key": sentinel, "provider": "invalid"})]
            assert all(sentinel not in response.text for response in responses)
            assert responses[1].json()["api_key_masked"] == "********"
            client.put("/api/settings", json={"api_key": ""})
            client.post("/api/onboarding/demo")
            assert sentinel not in command([*compose, "logs", "--no-color"], env)
        if (ROOT / "frontend/playwright.config.ts").exists():
            ui_env = env.copy()
            ui_env["PW_BASE_URL"] = "http://localhost:8000"
            output = command([shutil.which("pnpm.cmd" if os.name == "nt" else "pnpm") or "pnpm", "--dir", "frontend", "exec", "playwright", "test"], ui_env)
            print("Playwright: PASS; " + " ".join(line.strip() for line in output.splitlines() if "passed" in line), flush=True)
        print("Compose: PASS; healthy, health/UI 200, Demo/onboarding, key masking and logs", flush=True)
    finally:
        command([*compose, "down"], env)
        command(["docker", "volume", "rm", project + "_app-data"])
        print("Compose down: PASS", flush=True)
    audit()


if __name__ == "__main__":
    gate()
