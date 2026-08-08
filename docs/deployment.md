# EnergyForecast deployment

## Runtime topology

The supported container baseline is a six-service Docker Compose stack:

| Service | Purpose | Public exposure |
|---|---|---|
| `db` | PostgreSQL 17 + TimescaleDB 2.28.3 | development override only, localhost-bound |
| `migrate` | one-shot `alembic upgrade head` | none |
| `api` | FastAPI application process | edge network only through Nginx |
| `worker` | PostgreSQL-backed background worker | none |
| `web` | immutable React static image | edge network only through Nginx |
| `nginx` | same-origin edge proxy | localhost-bound by the supplied overrides |

`api` and `worker` do not start until the database is healthy and `migrate` exits successfully. The
backend network is internal and contains `db`, `migrate`, `api`, and `worker`; the edge network
contains only `nginx`, `web`, and `api`. The artifact volume is mounted only into the API and worker.

## Pinned image/tool baselines

| Component | Pinned reference |
|---|---|
| backend build/runtime | `python:3.13.14-slim-bookworm` |
| uv build tool | `ghcr.io/astral-sh/uv:0.12.2` |
| frontend build | `node:24.18.0-alpine` |
| static/edge Nginx | `nginx:1.27.5-alpine` |
| database | `timescale/timescaledb:2.28.3-pg17` |
| OpenAPI generator | `openapitools/openapi-generator-cli:v7.24.0` |
| secret scan | `zricethezav/gitleaks:v8.24.3` |
| container scan | `aquasec/trivy:0.58.2` |

Application images are tagged with `APP_VERSION` (default `0.1.0`) and record OCI version, source,
and `CODE_COMMIT` revision labels. Production-like configuration requires an explicit database
password, database URL, and commit identifier; no production image depends on a source bind mount.

## Development startup

Docker Compose automatically loads `docker-compose.override.yml` with the base file. From the
repository root:

```text
docker compose up --build
```

The edge is then available at `http://127.0.0.1:8080` and the development database is available at
`127.0.0.1:5432`. Override the host ports with `APP_HTTP_PORT` and `DB_PORT` if needed.

The SPA calls the generated SDK through the same-origin `/api/v1` base path. The edge proxy removes
that prefix before forwarding to FastAPI. It does not add a wildcard CORS policy.

## Production-like startup

The provided production-like overlay intentionally publishes only Nginx on loopback and leaves the
database private. Supply secrets through the environment or an external secret-management layer:

```text
POSTGRES_PASSWORD=<strong-password>
DATABASE_URL=postgresql+asyncpg://energyforecast:<strong-password>@db:5432/energyforecast
CODE_COMMIT=<immutable-git-sha>
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build --wait
```

The coursework baseline has no built-in authentication, so this topology is intended for localhost or
a protected private network. Internet-facing deployment requires an external access-control/TLS layer;
that is deliberately outside the application baseline.

## Hardening controls

- application, migration, static-web, and edge containers run with read-only root filesystems;
- backend and Nginx processes run as non-root users, drop Linux capabilities, and set
  `no-new-privileges`;
- writable temporary paths use bounded `tmpfs` mounts;
- raw uploads, model bundles, and exports live in the named `artifact_data` volume, never the webroot;
- `/artifacts/` is explicitly denied at the edge; controlled API downloads remain authoritative;
- the edge request body limit is `300m`, matching the backend `314572800`-byte upload limit;
- API upload proxying is streaming (`proxy_request_buffering off`) with explicit connection/body/read
  timeouts;
- security headers include CSP, frame denial, MIME sniffing protection, referrer and permissions
  policies;
- the database has no production host port and the backend network is internal.

## Health and readiness

`db` uses `pg_isready`. `migrate` is successful only with exit code zero. API health requires both the
existing `/health/ready` database check and a writable artifact root in the container health command.
The worker healthcheck verifies that the worker PID remains alive. `web` and `nginx` expose internal
`/healthz` endpoints. Compose dependencies use real health/completion states; no fixed startup sleeps
are required.

## Resource guidance

The default Compose file intentionally does not impose hardware-specific CPU or memory ceilings.
For a typical coursework workstation, reserve at least 2 CPU cores and 4 GiB RAM for the whole stack;
ML experiments may benefit from additional memory. Keep the worker parallelism and BLAS/thread limits
from the recorded ML execution profiles rather than increasing concurrency blindly.

## Backup and restore boundary

A complete backup consists of:

1. a PostgreSQL logical backup (`pg_dump`) taken from a consistent database state;
2. a copy/snapshot of the `artifact_data` named volume;
3. the application image version and immutable commit identifier;
4. SHA-256 metadata already stored for application-managed artifacts.

Database metadata and artifact bytes must be restored as one coordinated set. The artifact volume is
not exposed through Nginx and should not be copied into the repository.

## Verification

Static contract verification:

```text
python scripts/verify_infrastructure.py
```

Clean-volume runtime smoke on Linux/CI:

```text
bash scripts/compose-smoke.sh
```

The smoke test builds the images, starts a unique project with fresh volumes, waits for health states,
checks the SPA and proxied readiness endpoint, verifies the one-shot migration exit code, and removes
the project and volumes afterward.
