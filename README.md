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
- create the four chronological validation folds used by the ML experiments.

The API is built with FastAPI, PostgreSQL and TimescaleDB. The frontend is still a small React/Vite
shell. Model training and forecast endpoints are the next parts of the project.

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

## Run all checks

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

## License

This project is licensed under the [MIT License](LICENSE).
