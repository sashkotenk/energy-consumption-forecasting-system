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
    docker compose -f docker-compose.yml -f docker-compose.override.yml config | Out-Null
    Assert-LastExitCode -CommandName "development docker compose config"

    $oldPostgresPassword = $env:POSTGRES_PASSWORD
    $oldDatabaseUrl = $env:DATABASE_URL
    $oldCodeCommit = $env:CODE_COMMIT
    try {
        $env:POSTGRES_PASSWORD = "verification-only"
        $env:DATABASE_URL = "postgresql+asyncpg://energyforecast:verification-only@db:5432/energyforecast"
        $env:CODE_COMMIT = "verification"
        docker compose -f docker-compose.yml -f docker-compose.prod.yml config | Out-Null
        Assert-LastExitCode -CommandName "production docker compose config"
    }
    finally {
        $env:POSTGRES_PASSWORD = $oldPostgresPassword
        $env:DATABASE_URL = $oldDatabaseUrl
        $env:CODE_COMMIT = $oldCodeCommit
    }

    python scripts/verify_infrastructure.py
    Assert-LastExitCode -CommandName "infrastructure contract verification"

    docker compose -f docker-compose.yml -f docker-compose.override.yml up -d --wait db
    Assert-LastExitCode -CommandName "docker compose up -d --wait db"
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
    Invoke-Uv -Arguments @("run", "--frozen", "pytest", "-m", "ml_guard")
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

Push-Location $repositoryRoot
try {
    python scripts/verify_documentation.py
    Assert-LastExitCode -CommandName "documentation verification"

    if (Test-Path "docs/evidence/handoff-manifest.json") {
        python scripts/verify_evidence.py
        Assert-LastExitCode -CommandName "evidence checksum verification"
    }

    git diff --check
    Assert-LastExitCode -CommandName "git diff --check"

    $privatePaths = git ls-files | Select-String -Pattern '(^|/)(AGENTS\.md|prompts/|checklists?/|Пункт плану|План виконання|EnergyForecast-private)'
    if ($privatePaths) {
        throw "Private planning/specification material is tracked: $($privatePaths -join ', ')"
    }
}
finally {
    Pop-Location
}
