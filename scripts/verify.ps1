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

Push-Location (Join-Path $repositoryRoot "backend")
try {
    Invoke-Uv -Arguments @("sync", "--all-groups")
    Invoke-Uv -Arguments @("run", "ruff", "check", ".")
    Invoke-Uv -Arguments @("run", "ruff", "format", "--check", ".")
    Invoke-Uv -Arguments @("run", "mypy", "src", "tests")
    Invoke-Uv -Arguments @("run", "pytest")
}
finally {
    Pop-Location
}

Push-Location (Join-Path $repositoryRoot "frontend")
try {
    npm ci
    Assert-LastExitCode -CommandName "npm ci"
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
    docker compose -f docker-compose.yml config
    Assert-LastExitCode -CommandName "docker compose config"
}
finally {
    Pop-Location
}
