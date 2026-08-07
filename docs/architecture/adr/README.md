# Architecture Decision Record Index

All decisions are **Accepted for design baseline** and must be reviewed after implementation.

| ADR | Decision | Main consequence |
|---|---|---|
| ADR-001 | Modular monolith | simple delivery; enforce module boundaries |
| ADR-002 | Separate API and worker processes | reliable long-running jobs |
| ADR-003 | PostgreSQL-backed job queue | no broker in baseline; limited scale |
| ADR-004 | TimescaleDB only for temporal facts | clear metadata/time-series separation |
| ADR-005 | Application-materialized hourly version | quality policy remains explicit |
| ADR-006 | Artifact files outside DB | coordinated backup is mandatory |
| ADR-007 | OpenAPI-generated TypeScript client | contract drift detected in CI |
| ADR-008 | REST polling for progress | no WebSocket/SSE complexity |
| ADR-009 | No built-in authentication | deploy on localhost/private network |
| ADR-010 | Weather integration optional | W0 remains available offline |
| ADR-011 | Direct 24-horizon forecasting | one model façade, 24 target regressors |
| ADR-012 | No arbitrary model import | prevent unsafe pickle/joblib loading |
| ADR-013 | TimescaleDB 2.28 hypertable DDL | pinned runtime uses the current `CREATE TABLE ... WITH` API |
| ADR-014 | Job idempotency, retry and attempt history | replay returns the original job; attempt evidence is retained |
| ADR-015 | Import timezone and restart policy | explicit UCI timezone assumption; partial attempts are never valid |
| ADR-016 | Quality evidence and report versioning | raw invalid values are retained; reports are immutable and paginated |
| ADR-017 | Immutable hourly transformation versions | partial energy is unscaled; missing hours remain distinguishable from zero |
| ADR-018 | Bounded server-side analytics | version/range indexes and adaptive buckets keep browser payloads bounded |

For every implementation deviation, create a new ADR or supersede the corresponding entry rather than silently changing the code.
