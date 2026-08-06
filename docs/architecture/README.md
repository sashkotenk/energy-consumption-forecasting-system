
# Architecture baseline

This directory contains technical product documentation that is safe to version with the source code.

The root `ARCHITECTURE.md` is the concise snapshot of what is actually implemented. The design artifacts in this directory describe the intended system and are synchronized as implementation tasks land. Exact toolchain versions and executed verification evidence are recorded in `docs/implementation-log.md`.

- `adr/` — architecture decision index and future ADRs;
- `references/` — verified architecture and technical sources;
- `traceability.csv` — mapping of requirements to components, data, API and tests.

The full coursework planning and private workflow materials are deliberately kept in the sibling
private directory and must not be committed to this repository.

The current OpenAPI, DDL, diagrams and SAD files are design baselines. Whenever implementation differs from them, update the relevant ADR and synchronize the affected technical documentation in the same pull request.
