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

The API exposes `/health/live`, `/health/ready`, `/jobs`, `/datasets`, dataset-import staging and
lookup, `/docs`, and `/openapi.json`. Readiness
returns `503 application/problem+json` until `DATABASE_URL` points to an available PostgreSQL
database. `uv run energy-forecast-worker` starts the independent PostgreSQL polling process.

## Runtime settings

Settings are read from process environment variables and validated during process startup. See
the repository `.env.example` for the complete current list. `APP_PORT`, `MAX_UPLOAD_BYTES`,
`LOG_LEVEL`, CORS origins, paths, and process identity are typed. In `production`, both
`DATABASE_URL` and `CODE_COMMIT` are required; missing values stop startup before serving work.
Worker polling, heartbeat, stale timeout, recovery batch size, and one-cycle smoke mode are typed
settings. The heartbeat interval must remain shorter than the stale timeout.

The ignored root `.env` is suitable for local Compose and can be loaded explicitly when starting a
host API from `backend/`:

```bash
uv run --env-file ../.env energy-forecast-api
```

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

## Job queue

`SqlAlchemyJobQueue` owns short transactions for enqueue, claim, heartbeat, progress, completion,
cancellation, retry, and stale recovery. Claim uses `FOR UPDATE SKIP LOCKED` and commits before a
handler starts. `JobHandlerRegistry` prevents a worker from claiming types for which its process has
no handler. Handlers receive `JobExecutionContext` and must call `report_progress()` or
`raise_if_cancel_requested()` at safe checkpoints for cooperative cancellation.

An optional idempotency key returns the original job when all enqueue fields match and returns a
Problem Details conflict when the key is reused differently. Retry keeps the same job ID and stores
each claimed attempt in `app.job_attempts`, preserving prior stale/failure evidence.

The package uses a `src` layout. Dataset-import handlers are registered by the worker; experiment
and forecasting handlers are introduced with their application services.

## Model bundles

`ModelBundleService` writes only internal model artifacts through `ArtifactService`. A bundle stores
`manifest.json` and `model.joblib`; load verifies the persisted artifact checksum, manifest format,
model payload checksum, feature schema, horizon, dataset/version policy and library major versions
before calling `joblib.load`. Dataset upload routes never accept model files.

## Dataset catalog and uploads

Dataset CRUD uses short PostgreSQL transactions and reports dependent immutable versions/imports as
a conflict instead of cascading artifact removal. `POST /datasets/{datasetId}/imports` accepts
multipart `.csv` and `.txt` files, enforces `MAX_UPLOAD_BYTES` while streaming, sanitizes the
original filename and import options, and checks UTF-8 CSV-like structure independently of the
declared media type. Accepted bytes are stored under an opaque generated key with SHA-256 metadata.
The dataset version, import record and `dataset_import` job are then committed together and the API
returns only import/job identifiers. Full row parsing remains a worker responsibility.

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
