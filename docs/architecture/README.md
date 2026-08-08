# Architecture baseline

This directory contains technical product documentation that is safe to version with the source code.

The root `ARCHITECTURE.md` is the concise snapshot of what is actually implemented. The final English SAD is `docs/sad/SAD_v1.0.md`. Exact toolchain versions, executed verification evidence and release-readiness results are recorded in `docs/implementation-log.md` and `docs/evidence/`.

- `adr/` — accepted architecture decisions and their status;
- `references/` — verified architecture and technical sources;
- `traceability.csv` — requirement-to-component/code/data/API/test/evidence mapping.

The full coursework planning and private workflow materials are deliberately kept outside the repository and must not be committed here.

Runtime OpenAPI, Alembic migrations and passing tests are the executable sources of truth. `docs/api/openapi-design.yaml`, `docs/database/schema-design.sql`, diagrams, traceability and SAD are synchronized documentation. If implementation intentionally diverges from an accepted architectural decision or contract, update the relevant ADR and affected public technical documentation in the same pull request.
