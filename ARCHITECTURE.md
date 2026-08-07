# EnergyForecast architecture

## Implemented snapshot

The repository currently implements the TASK-09 transformation boundary, not the complete business
system described by the design documents.

```text
repository
├── backend     FastAPI/worker boundaries, SQLAlchemy models, Alembic and tests
├── frontend    Vite React TypeScript shell and unit smoke test
├── docs        design contracts, ADRs and implementation evidence
└── CI          backend with TimescaleDB plus independent frontend verification
```

The backend exposes FastAPI liveness/readiness endpoints, typed settings, structured JSON logging,
request correlation and a Problem Details error boundary. SQLAlchemy 2.x maps the complete `app`,
`ts`, and `ml` baseline, while Alembic creates PostgreSQL extensions, schemas, constraints, indexes
and three TimescaleDB hypertables. Async sessions are operation-scoped and transaction boundaries
are explicit. An application-owned artifact port now has a local adapter that streams bytes below a
configured private root, publishes by generated opaque keys, records SHA-256 and size, and persists
metadata through short PostgreSQL transactions. Reads resolve IDs through metadata, while deletion
checks database references before cleaning up bytes. The job application boundary now defines the
state machine, idempotency and bounded-retry rules. Its PostgreSQL adapter performs atomic short
claims, records attempt history, heartbeats active work and recovers stale ownership. FastAPI
provides enqueue/poll/cancel/retry operations, while the separate worker process executes only
registered handlers. The dataset module now exposes catalog CRUD and import lookup. Multipart
requests are bounded, sanitized and checked for CSV-like content before a generated-key raw artifact
is stored. A short PostgreSQL transaction then creates the immutable dataset version, import record,
and queued job together; failed staging compensates by deleting the unreferenced artifact. Dataset
imports produce versioned quality evidence. Accepted transformations atomically create a child
version, run and job. The worker applies the recorded duplicate/interpolation policy, integrates
interval power without scaling incomplete hours, and persists quality-labelled hourly facts in
TimescaleDB through restart-safe batches. Analytics and all ML handlers remain deferred.

## Intended system architecture

The accepted design baseline is a modular monolith deployed as separate API and worker processes from one Python codebase. A React single-page application uses the REST API. PostgreSQL with TimescaleDB stores metadata and time-series facts, while a local artifact-store adapter keeps large files outside the database.

```text
Browser → reverse proxy → React SPA / FastAPI API
                                  ↓
                         PostgreSQL/TimescaleDB
                                  ↑
                         background worker
                                  ↔ artifact store
```

Long-running work uses a PostgreSQL-backed job queue with short claiming transactions and
`FOR UPDATE SKIP LOCKED`; the claim transaction is never held during handler work. REST polling is
the progress mechanism. Redis, RabbitMQ, Celery, WebSocket, authentication, and microservices are
outside the coursework baseline.

## Dependency direction

Backend modules keep domain and application policies independent of FastAPI handlers, SQLAlchemy
sessions, storage paths, and scikit-learn implementations where practical. Readiness, artifact and
job ports are owned by application-facing modules; dataset orchestration likewise depends on catalog
and artifact ports rather than FastAPI or storage paths. The local filesystem and SQLAlchemy adapters
remain replaceable infrastructure details. Handler code depends on a job execution context rather
than directly on FastAPI or a SQLAlchemy session.

The planned frontend dependency direction is:

```text
app/pages/widgets → features/entities/shared → generated API client
```

Server state belongs in TanStack Query, form state in React Hook Form and Zod, route state in URL parameters, and local presentation state in React. A global mutable store is not part of the baseline.

## Authoritative technical baselines

- `docs/api/openapi-design.yaml`
- `docs/database/schema-design.sql`
- `docs/diagrams/`
- `docs/sad/SAD_draft_v0.1.md`
- `docs/architecture/adr/README.md`
- `docs/architecture/traceability.csv`

These documents describe planned and implemented components. Runtime OpenAPI for implemented routes, Alembic migrations, passing tests, and recorded ADRs supersede remaining design assumptions. Any deviation must be documented in the same change that introduces it.

## Reproducibility and safety constraints

- Python, Node and TimescaleDB/PostgreSQL versions are pinned; dependency lockfiles are committed.
- Raw data, uploads, model binaries, exports, secrets, database volumes, and local artifacts are ignored.
- Uploaded filenames are metadata only; generated storage keys are validated and never expose the
  configured absolute root.
- Artifact writes use a same-directory temporary file and atomic no-overwrite publication; failed
  streams and failed metadata persistence are cleaned up.
- Dataset uploads enforce the 300 MB application limit while streaming to storage, accept only
  generated-key `.csv`/`.txt` artifacts, sanitize client metadata, and inspect actual tabular text.
- Dataset deletion is rejected once immutable versions/imports exist; it never cascades into artifact
  byte deletion.
- Future model loading may accept only internally produced, checksum-verified bundles.
- Time-series preprocessing must preserve chronological order and prevent future-data leakage.
- A transformation never edits its source version or raw artifact; the child version records source,
  engine, policy, summary, coverage, interpolation and hourly quality status.
