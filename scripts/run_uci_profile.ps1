$ErrorActionPreference = "Stop"

if (-not $env:ENERGYFORECAST_UCI_PATH) {
    throw "Set ENERGYFORECAST_UCI_PATH to the external UCI household power file."
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
Push-Location (Join-Path $repositoryRoot "backend")
try {
    uv sync --all-groups --frozen
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed with exit code $LASTEXITCODE" }
    uv run --frozen pytest -m full_dataset tests/manual/test_uci_full_profile.py
    if ($LASTEXITCODE -ne 0) { throw "UCI profile failed with exit code $LASTEXITCODE" }
}
finally {
    Pop-Location
}
