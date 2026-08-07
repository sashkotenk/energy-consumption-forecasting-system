"""One-shot repository patch used to prepare TASK-17 on its feature branch."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"Expected text not found in {path}: {old[:80]!r}")
    target.write_text(text.replace(old, new), encoding="utf-8", newline="\n")


replace(
    "backend/src/energy_forecast/api.py",
    '        version=__version__,\n        description="Energy consumption analysis and forecasting API",',
    '        version=__version__,\n        openapi_version="3.1.0",\n        description="Energy consumption analysis and forecasting API",',
)

# Experiment operation IDs.
replace(
    "backend/src/energy_forecast/experiments/api.py",
    '@router.get("/algorithms", tags=["Experiments"], response_model=tuple[AlgorithmResponse, ...])',
    '@router.get(\n        "/algorithms",\n        tags=["Experiments"],\n        operation_id="listAlgorithms",\n        response_model=tuple[AlgorithmResponse, ...],\n    )',
)
replace(
    "backend/src/energy_forecast/experiments/api.py",
    '        tags=["Experiments"],\n        status_code=HTTPStatus.ACCEPTED,',
    '        tags=["Experiments"],\n        operation_id="createExperiment",\n        status_code=HTTPStatus.ACCEPTED,',
)
replace(
    "backend/src/energy_forecast/experiments/api.py",
    '@router.get("/experiments", tags=["Experiments"], response_model=ExperimentPageResponse)',
    '@router.get(\n        "/experiments",\n        tags=["Experiments"],\n        operation_id="listExperiments",\n        response_model=ExperimentPageResponse,\n    )',
)
replace(
    "backend/src/energy_forecast/experiments/api.py",
    '        "/experiments/{experimentId}",\n        tags=["Experiments"],\n        response_model=ExperimentResponse,',
    '        "/experiments/{experimentId}",\n        tags=["Experiments"],\n        operation_id="getExperiment",\n        response_model=ExperimentResponse,',
)
replace(
    "backend/src/energy_forecast/experiments/api.py",
    '        "/experiments/{experimentId}/comparison",\n        tags=["Experiments"],\n        response_model=ComparisonResponse,',
    '        "/experiments/{experimentId}/comparison",\n        tags=["Experiments"],\n        operation_id="compareExperiment",\n        response_model=ComparisonResponse,',
)
replace(
    "backend/src/energy_forecast/experiments/api.py",
    '        "/experiments/{experimentId}/cancel",\n        tags=["Experiments"],\n        response_model=ExperimentResponse,',
    '        "/experiments/{experimentId}/cancel",\n        tags=["Experiments"],\n        operation_id="cancelExperiment",\n        response_model=ExperimentResponse,',
)

# Forecast operation IDs.
replace(
    "backend/src/energy_forecast/forecasting/api.py",
    '        "",\n        status_code=HTTPStatus.CREATED,\n        response_model=ForecastResponse,',
    '        "",\n        operation_id="createForecast",\n        status_code=HTTPStatus.CREATED,\n        response_model=ForecastResponse,',
)
replace(
    "backend/src/energy_forecast/forecasting/api.py",
    '    @router.get("", response_model=ForecastPageResponse)',
    '    @router.get("", operation_id="listForecasts", response_model=ForecastPageResponse)',
)
replace(
    "backend/src/energy_forecast/forecasting/api.py",
    '        "/{forecastId}",\n        response_model=ForecastResponse,',
    '        "/{forecastId}",\n        operation_id="getForecast",\n        response_model=ForecastResponse,',
)

# Export operation IDs.
replace(
    "backend/src/energy_forecast/exports/api.py",
    '        "/forecasts/{forecastId}/exports",\n        status_code=HTTPStatus.CREATED,',
    '        "/forecasts/{forecastId}/exports",\n        operation_id="createForecastExport",\n        status_code=HTTPStatus.CREATED,',
)
replace(
    "backend/src/energy_forecast/exports/api.py",
    '        "/experiments/{experimentId}/exports",\n        status_code=HTTPStatus.CREATED,',
    '        "/experiments/{experimentId}/exports",\n        operation_id="createExperimentExport",\n        status_code=HTTPStatus.CREATED,',
)
replace(
    "backend/src/energy_forecast/exports/api.py",
    '        "/artifacts/{artifactId}/download",\n        response_class=StreamingResponse,',
    '        "/artifacts/{artifactId}/download",\n        operation_id="downloadExportArtifact",\n        response_class=StreamingResponse,',
)

# Frontend scripts and exact codegen dependency.
package_path = ROOT / "frontend/package.json"
package = json.loads(package_path.read_text(encoding="utf-8"))
package["scripts"]["api:generate"] = "openapi-ts"
package["scripts"]["api:check"] = (
    "npm run api:generate && git diff --exit-code -- ../docs/api/openapi.json src/generated/api"
)
package["devDependencies"]["@hey-api/openapi-ts"] = "0.99.0"
package_path.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8", newline="\n")

# CI drift gates.
replace(
    ".github/workflows/ci.yml",
    '      - name: Type check\n        run: uv run --frozen mypy src tests\n\n      - name: Upgrade database',
    '      - name: Type check\n        run: uv run --frozen mypy src tests\n\n      - name: Verify runtime OpenAPI artifact\n        run: uv run --frozen python ../scripts/export_openapi.py --check\n\n      - name: Upgrade database',
)
replace(
    ".github/workflows/ci.yml",
    '      - name: Install locked dependencies\n        run: npm ci\n\n      - name: Lint',
    '      - name: Install locked dependencies\n        run: npm ci\n\n      - name: Verify generated API SDK drift\n        run: npm run api:check\n\n      - name: Lint',
)

# Full repository verification drift gates.
replace(
    "scripts/verify.ps1",
    '    Invoke-Uv -Arguments @("run", "mypy", "src", "tests")\n    Invoke-Uv -Arguments @("run", "alembic", "upgrade", "head")',
    '    Invoke-Uv -Arguments @("run", "mypy", "src", "tests")\n    Invoke-Uv -Arguments @("run", "python", "../scripts/export_openapi.py", "--check")\n    Invoke-Uv -Arguments @("run", "alembic", "upgrade", "head")',
)
replace(
    "scripts/verify.ps1",
    '    npm ci\n    Assert-LastExitCode -CommandName "npm ci"\n    npm run lint',
    '    npm ci\n    Assert-LastExitCode -CommandName "npm ci"\n    npm run api:check\n    Assert-LastExitCode -CommandName "npm run api:check"\n    npm run lint',
)

# README: runtime contract and generated client are now available.
replace(
    "README.md",
    'The API is built with FastAPI, PostgreSQL and TimescaleDB. The frontend is still a small React/Vite\nshell. The experiment/forecast UI and generated API client are the next parts of the project.',
    'The API is built with FastAPI, PostgreSQL and TimescaleDB. Its OpenAPI 3.1 document is exported\ndeterministically and generates the committed TypeScript SDK under `frontend/src/generated/api`. The\nfrontend is still a small React/Vite shell; the product pages and experiment/forecast UI remain next.',
)
replace(
    "README.md",
    'npm run lint\nnpm run typecheck',
    'npm run api:check\nnpm run lint\nnpm run typecheck',
)
replace(
    "README.md",
    '- [`docs/api/openapi-design.yaml`](docs/api/openapi-design.yaml) — design-time OpenAPI contract;',
    '- [`docs/api/openapi.json`](docs/api/openapi.json) — authoritative exported runtime OpenAPI 3.1 contract;\n- [`docs/api/openapi-design.yaml`](docs/api/openapi-design.yaml) — design reference retained for planned-contract traceability;\n- [`frontend/src/generated/api/`](frontend/src/generated/api/) — generated TypeScript SDK; never edit generated files manually;',
)

# Architecture snapshot and authority boundary.
replace(
    "ARCHITECTURE.md",
    '├── frontend    Vite React TypeScript shell and unit smoke test',
    '├── frontend    Vite React TypeScript shell, generated API SDK and unit smoke test',
)
replace(
    "ARCHITECTURE.md",
    'The planned frontend dependency direction is:\n\n```text\napp/pages/widgets → features/entities/shared → generated API client\n```',
    'The frontend dependency direction is:\n\n```text\napp/pages/widgets → features/entities/shared → generated API client\n```\n\nFastAPI runtime OpenAPI 3.1 is exported deterministically to `docs/api/openapi.json`. The pinned\nOpenAPI generator consumes that artifact and writes `frontend/src/generated/api`; generated files are\nnot edited by hand. CI regenerates both layers and rejects drift before frontend compilation.',
)
replace(
    "ARCHITECTURE.md",
    '- `docs/api/openapi-design.yaml`\n- `docs/database/schema-design.sql`',
    '- `docs/api/openapi.json` — authoritative implemented API contract\n- `docs/api/openapi-design.yaml` — design reference for planned contract traceability\n- `docs/database/schema-design.sql`',
)
replace(
    "ARCHITECTURE.md",
    'These documents describe planned and implemented components. Runtime OpenAPI for implemented routes, Alembic migrations, passing tests, and recorded ADRs supersede remaining design assumptions.',
    'The exported runtime OpenAPI is authoritative for implemented routes and generated frontend types. Alembic migrations, passing tests, and recorded ADRs likewise supersede remaining design assumptions.',
)

# Traceability records the implemented contract/code-generation tests.
traceability = ROOT / "docs/architecture/traceability.csv"
text = traceability.read_text(encoding="utf-8")
old = 'FR-10,FastAPI and OpenAPI,none,/api/v1,contract'
new = 'FR-10,FastAPI OpenAPI and generated TypeScript SDK,openapi.json and generated/api,implemented FastAPI routes,OpenAPI 3.1 operation-id Problem Details enum and generation drift contract tests'
if old in text:
    text = text.replace(old, new)
elif new not in text:
    raise SystemExit("Expected FR-10 traceability row not found")
traceability.write_text(text, encoding="utf-8", newline="\n")

# Initial TASK-17 implementation record; exact CI evidence is appended after the PR gate.
implementation_log = ROOT / "docs/implementation-log.md"
log = implementation_log.read_text(encoding="utf-8")
marker = "## TASK-17 — OpenAPI synchronization and generated TypeScript SDK"
if marker not in log:
    log += '''\n\n## TASK-17 — OpenAPI synchronization and generated TypeScript SDK\n\n**Date:** 2026-08-08\n**Status:** implemented; pull-request CI verification pending\n\n**Scope:** authoritative FastAPI OpenAPI 3.1 export; stable explicit operation IDs for every\nimplemented endpoint; deterministic `docs/api/openapi.json`; exact-pinned TypeScript SDK generation\ninto `frontend/src/generated/api`; OpenAPI contract tests; and CI/full-gate drift verification.\nGenerated files are never hand-edited and no handwritten duplicate API DTO layer is introduced.\n\n### Dependency change\n\n- `@hey-api/openapi-ts` 0.99.0 is pinned exactly as a frontend development dependency for\n  deterministic OpenAPI-to-TypeScript generation. No backend runtime dependency changed.\n\n### Contract and architecture impact\n\nThe implemented FastAPI schema is the authority for implemented HTTP contracts.\n`docs/api/openapi-design.yaml` remains a design reference, while the deterministic JSON export is\nthe code-generation input. CI checks both runtime-schema drift and generated-SDK drift. No database\nschema, DDL or Alembic migration changes are required.\n\nExact verification commands and outcomes are recorded after the feature-branch gate completes.\nTASK-18 has not been started.\n'''
    implementation_log.write_text(log, encoding="utf-8", newline="\n")

print("TASK-17 repository patch prepared")
