# EnergyForecast

EnergyForecast is a course-project software system for analysing hourly electricity consumption and producing a direct 24-hour forecast with machine-learning methods.

> Українською: EnergyForecast — програмна система для аналізу погодинного споживання електроенергії та формування прямого прогнозу на наступні 24 години методами машинного навчання.

## Current status

TASK-10 adds bounded analytical queries on top of streaming ingestion, deterministic quality
evaluation, immutable hourly transformations, persistence, artifact, and job foundations:

- an installable Python 3.13 `src`-layout package managed by uv;
- typed environment configuration with production startup validation;
- FastAPI liveness/readiness routes, request IDs, JSON logs, and Problem Details errors;
- SQLAlchemy 2.x mappings for the `app`, `ts`, and `ml` schemas;
- Alembic migrations for all tables, constraints, indexes and TimescaleDB hypertables;
- a pinned TimescaleDB 2.28.3 / PostgreSQL 17 Compose database;
- explicit async session and transaction boundaries with repository integration tests;
- an application-owned artifact port and a local filesystem adapter with generated opaque keys;
- streamed SHA-256/size calculation, atomic collision-safe publication, and failed-write cleanup;
- PostgreSQL artifact metadata, checksum lookup, controlled reads, and reference-checked deletion;
- atomic multi-worker claims through short `FOR UPDATE SKIP LOCKED` transactions;
- handler registry, heartbeat/progress reporting, cooperative cancellation, bounded retry, and
  stale-worker recovery;
- idempotent enqueue, polling, cancel, and retry endpoints with retained attempt evidence;
- dataset list/detail/create/update/delete endpoints with pagination and dependency-safe deletion;
- bounded multipart `.csv`/`.txt` staging with filename and option sanitization plus content checks;
- immutable raw artifacts and atomic dataset-version/import/job creation returning `202 Accepted`;
- fixed official-nine-column UCI parsing and explicitly mapped generic CSV parsing;
- bounded structural preview, delimiter/decimal detection, timezone and target-unit normalization;
- chunked raw-measurement inserts with source-row parse errors and restart-safe worker attempts;
- versioned quality reports for order, interval, gaps, duplicates, missing/non-finite values,
  physical invalidity and informational robust-z anomalies;
- bounded, paginated quality issue evidence through the dataset-version API;
- explicit duplicate resolution and bounded linear interpolation of gaps up to five minutes;
- interval-aware energy integration, unscaled partial hours, and persisted hourly coverage evidence;
- immutable derived dataset versions with reproducible transformation manifests and worker jobs;
- scoped summary, series, local-time profile, heatmap and distribution analytics endpoints;
- deterministic UTC-anchored server aggregation with enforced range and point-count bounds;
- explicit kWh, timezone, coverage and quality metadata for every analytical response;
- separate runnable API and worker processes from the same backend package;
- a Vite React TypeScript application managed by npm;
- linting, formatting, type checking, unit smoke tests, and production builds;
- separate cached backend and frontend GitHub Actions jobs.

ML pipelines remain assigned to later tasks. Raw invalid values and statistical peaks remain
immutable evidence; transformations materialize a new version without changing source rows or raw
artifacts, and analytics only reads those materialized hourly facts.

## Toolchain

| Area | Pinned baseline |
|---|---|
| Python | 3.13.14 |
| Python project manager | uv 0.12.2 |
| Node.js | 24.18.0 LTS |
| Frontend package manager | npm with committed `package-lock.json` |

Resolved application and development dependency versions are recorded in [`docs/implementation-log.md`](docs/implementation-log.md).

## Repository layout

```text
backend/                 Python package and backend tests
frontend/                React application and frontend tests
infrastructure/          reserved for deployment assets
tests/                   reserved for repository-level system tests
docs/                    versioned product technical documentation
.github/workflows/       continuous integration
scripts/                 repository verification helpers
```

Private prompts, coursework planning files, raw datasets, uploaded files, generated models, local artifacts, and secrets do not belong in this repository.

## Backend development

Install [uv](https://docs.astral.sh/uv/) and run the following commands from `backend/`:

```bash
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
```

The committed `.python-version` causes uv to provision Python 3.13.14 when it is not already installed.

## Frontend development

Use the Node version in `.nvmrc`, then run the following commands from `frontend/`:

```bash
npm ci
npm run dev
```

Frontend verification:

```bash
npm run lint
npm run typecheck
npm run test -- --run
npm run build
```

The starter interface and user-facing text are Ukrainian, while code and technical documentation use English.

## Verify the complete baseline

On PowerShell, run from the repository root:

```powershell
./scripts/verify.ps1
```

The script starts the pinned database, applies and drift-checks migrations, runs the real TimescaleDB
integration tests, runs the remaining backend/frontend checks, and validates `docker-compose.yml`.

## Database demonstration

Install Docker Desktop and uv, then run from the repository root in PowerShell:

```powershell
docker compose up -d --wait db
Set-Location backend
python -m uv sync --all-groups
python -m uv run alembic upgrade head
python -m uv run alembic check
$env:TEST_DATABASE_URL = "postgresql+asyncpg://energyforecast:energyforecast@localhost:5432/energyforecast"
python -m uv run pytest tests/integration/test_database_migrations.py `
  tests/integration/test_repositories.py -v
```

To show the created schemas and hypertables:

```powershell
Set-Location ..
docker compose exec db psql -U energyforecast -d energyforecast -c "\dn"
docker compose exec db psql -U energyforecast -d energyforecast `
  -c "SELECT hypertable_schema, hypertable_name FROM timescaledb_information.hypertables ORDER BY 1, 2;"
```

Start the API with the host-accessible database URL:

```powershell
Set-Location backend
python -m uv run --env-file ../.env energy-forecast-api
```

Open `http://localhost:8000/docs` or request `http://localhost:8000/health/ready`. Stop the local
database later with `docker compose stop db`; data remains in the named volume.

Start the independent worker in another terminal with the same `DATABASE_URL`:

```powershell
Set-Location backend
python -m uv run --env-file ../.env energy-forecast-worker
```

## Architecture and contracts

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — implemented architecture snapshot;
- [`docs/api/openapi-design.yaml`](docs/api/openapi-design.yaml) — design-time OpenAPI contract;
- [`docs/database/schema-design.sql`](docs/database/schema-design.sql) — design-time PostgreSQL/TimescaleDB schema;
- [`docs/diagrams/`](docs/diagrams/) — C4, UML, sequence, ER, deployment, and ML diagrams;
- [`docs/sad/SAD_draft_v0.1.md`](docs/sad/SAD_draft_v0.1.md) — draft Software Architecture Document;
- [`docs/architecture/traceability.csv`](docs/architecture/traceability.csv) — requirement traceability baseline.

## Environment configuration

Copy `.env.example` to `.env` only when a later runtime task requires it. Never commit `.env` or real credentials.

## License

This project is licensed under the [MIT License](LICENSE).
