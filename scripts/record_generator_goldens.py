import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.cache.store import Store
from backend.tests.test_generator import GOLDENS, MODES, prepare
from backend.agents.generator import Generator
from backend.models.generation import GenerationOptions

GOLDENS.mkdir(parents=True, exist_ok=True)
store = Store("data/golden-recording.sqlite3")
for fixture in ["coingecko", "frankfurter"]:
    spec, _, _, profile = prepare(store, fixture)
    for mode in MODES:
        code = Generator().render(spec, GenerationOptions(mode=mode), profile)
        (GOLDENS / f"{fixture}_{mode}.py").write_text(code, encoding="utf-8")
print("Recorded 12 deterministic generator goldens")
