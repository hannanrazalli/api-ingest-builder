$ErrorActionPreference = "Stop"
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    uv sync --frozen
    if ($LASTEXITCODE) { throw "uv sync --frozen failed" }
    pnpm --dir frontend install --frozen-lockfile
    if ($LASTEXITCODE) { throw "pnpm install failed" }
    pnpm --dir frontend build
    if ($LASTEXITCODE) { throw "Frontend build failed" }
    uv run --no-env-file uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
    if ($LASTEXITCODE) { throw "Backend failed" }
} finally { Pop-Location }
