# EnergyForecast

EnergyForecast is a course-project software system for analysing hourly electricity consumption and producing a direct 24-hour forecast with machine-learning methods.

> Українською: EnergyForecast — програмна система для аналізу погодинного споживання електроенергії та формування прямого прогнозу на наступні 24 години методами машинного навчання.

## Current status

TASK-01 establishes the monorepository and continuous-integration baseline:

- an installable Python 3.13 `src`-layout package managed by uv;
- a Vite React TypeScript application managed by npm;
- linting, formatting, type checking, unit smoke tests, and production builds;
- separate cached backend and frontend GitHub Actions jobs.

Business capabilities, API routes, database migrations, background workers, and ML pipelines are intentionally deferred to later tasks. The files under `docs/api`, `docs/database`, `docs/diagrams`, and `docs/sad` remain design-time baselines until their corresponding features are implemented.

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

The script runs the backend and frontend checks and validates `docker-compose.yml`. The Compose file is intentionally an empty valid baseline in TASK-01; runnable services are added by later infrastructure tasks.

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
