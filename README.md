# EnergyForecast

EnergyForecast is my course project for importing electricity readings, preparing an hourly time
series and forecasting consumption for the next 24 hours.

## What works now

The project can currently:

- upload UCI or mapped CSV data and process imports in a background worker;
- keep raw uploads and prepared dataset versions separate;
- report data-quality problems, clean short gaps and aggregate readings by hour;
- calculate summaries, profiles, heatmaps, distributions and bounded time series;
- build leakage-safe lag, rolling and calendar features with direct 24-hour targets;
- create the four chronological validation folds used by the ML experiments;
- train direct Ridge, Random Forest and HistGradientBoosting models;
- run queued experiments with four-fold chronological validation and deterministic model selection;
- compare persisted fold/horizon metrics and save checksum-verified model bundles;
- create reproducible 24-hour forecasts with provenance and a daily energy total;
- export forecast CSV and chart-ready JSON plus experiment metrics/manifest data as checksum-tracked
  artifacts, then download only export-purpose artifacts through a controlled endpoint;
- run as a hardened six-service Docker Compose stack with an explicit migration gate, separate API
  and worker processes, private PostgreSQL/TimescaleDB, non-root static/edge containers and same-origin
  `/api/v1` proxying.

The API is built with FastAPI, PostgreSQL and TimescaleDB. Its OpenAPI 3.1 document is exported
deterministically and generates the committed TypeScript SDK under `frontend/src/generated/api`. The
React/Vite frontend provides Ukrainian workflows for dataset import and analysis, experiment creation
and terminal-state handling, baseline model comparison, 24-hour forecast review and controlled
exports.

## Toolchain

| Area | Pinned baseline |
|---|---|
| Python | 3.13.14 |
| Python project manager | uv 0.12.2 |
| Node.js | 24.18.0 LTS |
| Frontend package manager | npm with committed `package-lock.json` |
| PostgreSQL / TimescaleDB | PostgreSQL 17 / TimescaleDB 2.28.3 |
| Nginx runtime | 1.30.4 / Alpine 3.24 |

Resolved application/development dependency versions and executed verification evidence are recorded
in [`docs/implementation-log.md`](docs/implementation-log.md).

## Repository layout

```text
backend/                 Python package, backend container and backend tests
frontend/                React application, static container and frontend tests
infrastructure/          edge proxy deployment assets
tests/                   reserved for repository-level system tests
docs/                    versioned product technical documentation
.github/workflows/       continuous integration
scripts/                 repository and deployment verification helpers
```

Private prompts, coursework planning files, raw datasets, uploaded files, generated models, local
artifacts, and secrets do not belong in this repository.

## Run the complete product

Install Docker with the Compose plugin and run from the repository root:

```text
docker compose up --build
```

The development override publishes the application at `http://127.0.0.1:8080` and PostgreSQL at
`127.0.0.1:5432`. Compose waits for database health and the one-shot Alembic migration before API and
worker startup. Stop and remove the stack with:

```text
docker compose down
```

See [`docs/deployment.md`](docs/deployment.md) for the production-like overlay, security controls,
health model, resource guidance and backup boundary.

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
npm run api:check
npm run lint
npm run typecheck
npm run test -- --run
npm run build
```

The user-facing interface and text are Ukrainian, while code and technical documentation use English.

## Run all checks

On PowerShell, run from the repository root:

```powershell
./scripts/verify.ps1
```

The script validates development/production Compose models and hardening, starts the pinned database
using health-state waiting, applies and drift-checks migrations, runs the mandatory ML guards and the
remaining backend/frontend verification, then checks whitespace and accidental private tracked paths.

Linux/CI can additionally validate a fresh full stack with:

```text
bash scripts/compose-smoke.sh
```

## Direct database/API development

For direct host development, start only the development database:

```powershell
docker compose up -d --wait db
Set-Location backend
python -m uv sync --all-groups
$env:DATABASE_URL = "postgresql+asyncpg://energyforecast:energyforecast@localhost:5432/energyforecast"
$env:TEST_DATABASE_URL = $env:DATABASE_URL
python -m uv run alembic upgrade head
python -m uv run alembic check
python -m uv run energy-forecast-api
```

Open `http://localhost:8000/docs` or request `http://localhost:8000/health/ready`. Start the worker in
another terminal with the same `DATABASE_URL`:

```powershell
Set-Location backend
python -m uv run energy-forecast-worker
```

## Architecture and contracts

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — implemented architecture snapshot;
- [`docs/deployment.md`](docs/deployment.md) — container topology and deployment hardening;
- [`docs/api/openapi.json`](docs/api/openapi.json) — authoritative exported runtime OpenAPI 3.1 contract;
- [`docs/api/openapi-design.yaml`](docs/api/openapi-design.yaml) — design reference retained for planned-contract traceability;
- [`frontend/src/generated/api/`](frontend/src/generated/api/) — generated TypeScript SDK; never edit generated files manually;
- [`docs/database/schema-design.sql`](docs/database/schema-design.sql) — design-time PostgreSQL/TimescaleDB schema;
- [`docs/diagrams/`](docs/diagrams/) — C4, UML, sequence, ER, deployment, and ML diagrams;
- [`docs/sad/SAD_draft_v0.1.md`](docs/sad/SAD_draft_v0.1.md) — draft Software Architecture Document;
- [`docs/architecture/traceability.csv`](docs/architecture/traceability.csv) — requirement traceability baseline.

## License

This project is licensed under the [MIT License](LICENSE).
