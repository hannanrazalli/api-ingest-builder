$ErrorActionPreference = "Stop"
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    docker compose --env-file .env.example build
    if ($LASTEXITCODE) { throw "Docker build failed" }
} finally { Pop-Location }
