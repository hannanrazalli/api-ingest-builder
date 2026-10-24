"""Exercise a disposable production container without loading dotenv or using real keys."""
import os
import subprocess
from uuid import uuid4

name = "aib-smoke-" + uuid4().hex[:10]


def docker(*args):
    return subprocess.run(["docker", *args], check=True, capture_output=True, text=True).stdout


check = r"""
import importlib.util
import json
import os
import shutil
import time
import urllib.request

base = "http://127.0.0.1:8000"
for _ in range(40):
    try:
        urllib.request.urlopen(base + "/api/health", timeout=1)
        break
    except OSError:
        time.sleep(.25)
else:
    raise RuntimeError("Container did not start")

def api(path, method="GET", data=None):
    request = urllib.request.Request(base + path, method=method,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(request, timeout=3))

assert api("/api/health")["phase"] == 7
assert "API Ingest Builder" in urllib.request.urlopen(base).read().decode()
assert api("/api/settings")["demo_mode"]
assert not api("/api/settings")["onboarded"]
saved = api("/api/settings", "PUT", {"api_key": "smoke-only-placeholder", "model_fast": "configured"})
assert saved["api_key_masked"] == "********"
assert "smoke-only-placeholder" not in json.dumps(saved)
assert api("/api/onboarding/demo", "POST")["demo_mode"]
job = api("/api/jobs", "POST")
from backend.cache.store import Store
from backend.models import Job
store = Store("data/app.sqlite3")
store.save_job(Job(id=job["id"], status="success"))
body = urllib.request.urlopen(base + "/api/jobs/" + job["id"] + "/events").read().decode()
assert "event: agent" in body and "event: done" in body
assert os.getuid() != 0
assert shutil.which("node") is None
assert shutil.which("codex") is None
assert api("/api/providers/codex/status")["code"] == "cli_missing"
assert importlib.util.find_spec("playwright") is None
print("PASS: HTTP, static export, onboarding, key masking, Demo, SSE, non-root, no Node/Playwright")
"""

try:
    docker("run", "-d", "--name", name, "-v", "/app/data", os.getenv("SMOKE_IMAGE", "api-ingest-builder-app"))
    print(docker("exec", name, "python", "-c", check).strip())
    docker("restart", name)
    persistence = check[:check.index('assert api("/api/health")')] + r"""
assert api("/api/settings")["onboarded"]
assert api("/api/settings")["demo_mode"]
assert api("/api/settings")["api_key_masked"] == "********"
print("PASS: SQLite settings persist across container restart")
"""
    print(docker("exec", name, "python", "-c", persistence).strip())
finally:
    subprocess.run(["docker", "rm", "-f", "-v", name], check=False, capture_output=True)
