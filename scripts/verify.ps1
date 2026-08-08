$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$uvExecutable = Get-Command uv -ErrorAction SilentlyContinue

function Invoke-Uv {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    if ($null -ne $script:uvExecutable) {
        & $script:uvExecutable.Source @Arguments
    }
    else {
        python -m uv @Arguments
    }

    if ($LASTEXITCODE -ne 0) {
        throw "uv command failed with exit code $LASTEXITCODE"
    }
}

function Assert-LastExitCode {
    param([Parameter(Mandatory = $true)][string]$CommandName)

    if ($LASTEXITCODE -ne 0) {
        throw "$CommandName failed with exit code $LASTEXITCODE"
    }
}

Push-Location $repositoryRoot
try {
    docker compose -f docker-compose.yml config
    Assert-LastExitCode -CommandName "docker compose config"
    docker compose -f docker-compose.yml up -d db
    Assert-LastExitCode -CommandName "docker compose up -d db"
    Start-Sleep -Seconds 5
}
finally {
    Pop-Location
}
$env:DATABASE_URL = "postgresql+asyncpg://energyforecast:energyforecast@localhost:5432/energyforecast"
$env:TEST_DATABASE_URL = $env:DATABASE_URL

Push-Location (Join-Path $repositoryRoot "backend")
try {
    Invoke-Uv -Arguments @("sync", "--all-groups", "--frozen")
    Invoke-Uv -Arguments @("run", "--frozen", "ruff", "check", ".")
    Invoke-Uv -Arguments @("run", "--frozen", "ruff", "format", "--check", ".")
    Invoke-Uv -Arguments @("run", "--frozen", "mypy", "src", "tests")
    Invoke-Uv -Arguments @("run", "--frozen", "python", "../scripts/export_openapi.py", "--check")
    Invoke-Uv -Arguments @("run", "--frozen", "alembic", "upgrade", "head")
    Invoke-Uv -Arguments @("run", "--frozen", "alembic", "check")
    Invoke-Uv -Arguments @("run", "--frozen", "pytest", "-m", "not performance and not full_dataset")
}
finally {
    Pop-Location
}

Push-Location (Join-Path $repositoryRoot "frontend")
try {
    npm ci
    Assert-LastExitCode -CommandName "npm ci"
    npm run api:check
    Assert-LastExitCode -CommandName "npm run api:check"
    npm run lint
    Assert-LastExitCode -CommandName "npm run lint"
    npm run typecheck
    Assert-LastExitCode -CommandName "npm run typecheck"
    npm run test -- --run
    Assert-LastExitCode -CommandName "npm run test -- --run"
    npm run build
    Assert-LastExitCode -CommandName "npm run build"
}
finally {
    Pop-Location
}
