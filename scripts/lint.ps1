$ErrorActionPreference = "Stop"
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    uv sync --frozen
    if ($LASTEXITCODE) { throw "uv sync --frozen failed" }
    uv run --no-env-file ruff check backend
    if ($LASTEXITCODE) { throw "Ruff check failed" }
    uv run --no-env-file ruff format --check backend
    if ($LASTEXITCODE) { throw "Ruff format failed" }
    pnpm --dir frontend install --frozen-lockfile
    if ($LASTEXITCODE) { throw "pnpm install failed" }
    pnpm --dir frontend lint
    if ($LASTEXITCODE) { throw "Frontend lint failed" }
} finally { Pop-Location }
