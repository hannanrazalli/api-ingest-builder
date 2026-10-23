$ErrorActionPreference = "Stop"
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    uv sync --frozen
    if ($LASTEXITCODE) { throw "uv sync --frozen failed" }
    uv run --no-env-file pytest
    if ($LASTEXITCODE) { throw "Backend tests failed" }
    pnpm --dir frontend install --frozen-lockfile
    if ($LASTEXITCODE) { throw "pnpm install failed" }
    pnpm --dir frontend test
    if ($LASTEXITCODE) { throw "Frontend type checks failed" }
} finally { Pop-Location }
