# Release security review

**Scope:** EnergyForecast coursework release candidate through TASK-22.

This review records implemented controls and known boundaries. It is not a claim that the single-user coursework release is suitable for direct Internet exposure.

## Upload and file handling

- Upload size is bounded by the application setting and aligned with the edge proxy limit (300 MiB / 314,572,800 bytes).
- Import parsing validates structure and supported data semantics; missing measurements are not converted to zero.
- User filenames are metadata only. Artifact storage keys are generated server-side and artifact bytes are stored outside the web root.
- Artifact download responses are resolved by controlled artifact IDs; storage paths are not exposed as download URLs.
- CSV exports neutralize spreadsheet-formula prefixes in text cells.

Evidence: backend upload-security, artifact and export tests; `docs/deployment.md`; ADR-024.

## Path traversal and artifact boundaries

- Local artifact-store keys are validated before filesystem access.
- Raw source artifacts, model bundles and generated exports are separated by artifact purpose and metadata.
- Direct edge requests to `/artifacts/` are rejected; controlled API download routes retrieve bytes by artifact ID.
- API/worker are the only application services mounting the artifact volume in the production-like Compose topology.

Evidence: `backend/tests/unit/test_local_artifact_store.py`, `backend/tests/integration/test_artifact_service.py`, infrastructure contract verification and ADR-024/ADR-025.

## SQL injection and transaction boundaries

- Persistence uses SQLAlchemy-bound parameters rather than constructing SQL from request values.
- One request/worker operation obtains its own async session through repository/session factories.
- Long parsing and model-training work is not performed inside a database transaction; job claiming and persistence use short transaction boundaries.
- PostgreSQL is not published in the production-like Compose topology.

Evidence: repository/integration tests, `ARCHITECTURE.md`, `docs/deployment.md`, ADR-014 and ADR-025.

## CORS and network exposure

- CORS origins are an explicit validated configuration value; the edge proxy does not synthesize wildcard CORS headers.
- Only the edge proxy is intended to be externally published in the production-like topology.
- Database, migration and worker services remain on private backend networks; only the API bridges backend and edge networks.

Known boundary: the coursework release has no authentication. External deployment requires an authenticated TLS gateway and a deployment-specific threat review.

## Secrets and private material

- Production dependencies are locked.
- Pull-request CI runs Gitleaks over Git history and rejects tracked private planning/specification paths.
- The repository contains `.env.example`, not plaintext production credentials.
- CI uses repository read-only permissions and does not require plaintext application secrets for pull requests.
- Raw UCI data, uploads, generated model bundles, database volumes and private coursework material are excluded from the release repository.

## Model deserialization

- User-supplied pickle/joblib data is never accepted as a model bundle.
- Internal model bundles carry cryptographic checksum and compatibility metadata.
- Forecasting verifies the bundle checksum and expected schema/runtime compatibility before deserialization.
- Artifact access remains internal/controlled rather than accepting an arbitrary filesystem path or URL.

Evidence: `backend/tests/integration/test_model_bundles.py`, forecast tests and ADR-020/ADR-023.

## Dependency and container posture

Required CI gates include backend/frontend dependency audit, Gitleaks/private-path scan and Trivy HIGH/CRITICAL scanning of backend, web and edge images. Application/proxy containers run non-root with read-only root filesystems, dropped capabilities and `no-new-privileges`; bounded tmpfs mounts provide required writable runtime paths.

## Deferred risks

- Authentication/authorization is deliberately outside the coursework baseline.
- TLS termination and public-network rate limiting belong to an external deployment gateway.
- The frontend production bundle has a known chunk-size warning; this is a performance/maintainability concern rather than a security bypass.
- Full UCI profiling remains an external-source verification because the 126+ MiB dataset is intentionally not committed.
