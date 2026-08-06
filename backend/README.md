# EnergyForecast backend

Install the locked development environment and run the backend checks:

```bash
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
```

If `uv` is not on `PATH`, use `python -m uv` for the same commands.

## Process entrypoints

After `uv sync --all-groups`, run the FastAPI process with:

```bash
uv run energy-forecast-api
```

The API exposes `/health/live`, `/health/ready`, `/docs`, and `/openapi.json`. Readiness
returns `503 application/problem+json` until `DATABASE_URL` points to an available PostgreSQL
database. The worker boundary can be validated with `uv run energy-forecast-worker`; it only
initializes configuration and logging until the PostgreSQL queue is implemented.

## Environment configuration

Settings are read from process environment variables and validated during process startup. See
the repository `.env.example` for the complete current list. `APP_PORT`, `MAX_UPLOAD_BYTES`,
`LOG_LEVEL`, CORS origins, paths, and process identity are typed. In `production`, both
`DATABASE_URL` and `CODE_COMMIT` are required; missing values stop startup before serving work.

Every log record is one JSON object and includes service, environment, code commit, correlation
context, duration and error fields. An incoming safe `X-Request-ID` is preserved; otherwise the API
generates one and returns it in the response. Client errors use Ukrainian RFC-style Problem Details,
while exception tracebacks remain only in logs.

## Artifact storage

`ArtifactService` is the application boundary for storing, finding, opening, and deleting artifact
content. Construct `LocalArtifactStore` with `Settings.artifact_root` and pair it with
`SqlAlchemyArtifactMetadataRepository`. The filesystem adapter accepts only generated opaque keys,
keeps original filenames as metadata, streams writes, computes SHA-256 and byte size, and publishes
completed files atomically without overwriting a collision. Database metadata maps the application
`purpose` to the existing `app.artifacts.kind` column.

The package uses a `src` layout. Dataset, queue and forecasting business modules are introduced by
later implementation tasks.

## Database and migrations

Start the pinned TimescaleDB service from the repository root, then run Alembic from `backend/`:

```bash
docker compose up -d --wait db
cd backend
uv run alembic upgrade head
uv run alembic check
```

The local Alembic default uses `localhost:5432`. Application containers use the `db` hostname from
`.env.example`. The mappings cover the `app`, `ts`, and `ml` schemas. The three temporal fact tables
are native TimescaleDB hypertables. See `migrations/README.md` for the downgrade policy.

Real database integration tests create disposable databases through `TEST_DATABASE_URL`:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://energyforecast:energyforecast@localhost:5432/energyforecast \
  uv run pytest -m integration
```
