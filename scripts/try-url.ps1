param([Parameter(Mandatory=$true, Position=0)][string]$Url, [switch]$Demo, [switch]$Force)
$ErrorActionPreference = "Stop"
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    $pipelineArgs = @("run", "--no-env-file", "python", "-m", "backend.cli", $Url)
    if ($Demo) { $pipelineArgs += "--demo" }
    if ($Force) { $pipelineArgs += "--force" }
    uv @pipelineArgs
    if ($LASTEXITCODE) { throw "Research failed or requires budget approval" }
} finally { Pop-Location }
