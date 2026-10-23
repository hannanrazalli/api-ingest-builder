"""Regenerate offline deterministic SQL artifacts; review changes before committing."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.converter import pandas_emitter, pyspark_emitter
from backend.converter.compiler import parse

root = Path(__file__).resolve().parents[1]/"backend"
output = root/"tests/golden/sql"
output.mkdir(exist_ok=True)
for case in json.loads((root/"fixtures/sql/cases.json").read_text()):
    for target, emitter in [("pandas",pandas_emitter),("pyspark",pyspark_emitter)]:
        (output/(case["name"]+"."+target+".py")).write_text(emitter.emit(parse(case["sql"])),encoding="utf-8",newline="\n")
print("39 SQL cases, 78 golden artifacts")
