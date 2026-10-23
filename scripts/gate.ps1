$ErrorActionPreference = "Stop"
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    uv run --no-env-file python scripts/phase_gate.py
    if ($LASTEXITCODE) { throw "Phase gate failed" }
} finally { Pop-Location }
