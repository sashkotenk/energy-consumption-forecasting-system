# ADR-025 — Hardened Compose edge deployment

**Status:** Accepted

## Context

The implemented product already separates API and worker processes, persists temporal facts in
PostgreSQL/TimescaleDB, stores large artifacts outside the database, and exposes generated frontend
contracts. The remaining deployment baseline must preserve those boundaries while making a clean
coursework installation reproducible and preventing direct exposure of internal services or artifact
paths.

## Decision

Use one versioned backend image for both `api`, `worker`, and the one-shot `migrate` service, plus a
multi-stage React static image, a dedicated Nginx edge image, and the pinned TimescaleDB image. Docker
Compose defines exactly `db`, `migrate`, `api`, `worker`, `web`, and `nginx`.

The database joins only an internal backend network. Nginx and the static web container join only the
edge network; the API joins both. The artifact volume is mounted only by API and worker. API and
worker wait for database health and successful migrations. Production-like configuration has no
source bind mounts and requires explicit database credentials and immutable commit metadata.

The edge proxy serves the SPA and forwards `/api/v1/` to FastAPI with the prefix stripped. It enforces
the same 300 MiB upload ceiling as the application, streams upload request bodies, sets bounded
timeouts and security headers, does not synthesize wildcard CORS, and denies direct `/artifacts/`
paths. Application and proxy containers run non-root with capability drops, read-only root filesystems,
`no-new-privileges`, and explicit temporary filesystems where compatible.

## Consequences

- `docker compose up --build` becomes the canonical local product startup.
- Migrations are an explicit deployment gate instead of API startup side effects.
- Same-origin browser traffic uses `/api/v1`, avoiding a public cross-origin API dependency.
- The database and artifact store remain inaccessible from the edge container.
- Production internet exposure still needs external authentication/access control and TLS because the
  application intentionally has no built-in authentication.
- CI can build and smoke the exact deployment topology with fresh named volumes and scan immutable
  image references.
