from pathlib import Path

path = Path("docs/implementation-log.md")
text = path.read_text(encoding="utf-8")
old = '''## TASK-16 — Exports and controlled downloads

**Date:** 2026-08-07
**Status:** implemented; repository-wide CI verification pending

Implemented the bounded export boundary on top of the existing forecast, experiment and Artifact
services. Forecast results serialize to fixed-column UTF-8 CSV or chart-ready JSON. Completed
experiments serialize persisted comparison metrics to normalized CSV or structured JSON and expose
the canonical persisted result manifest as JSON. Every generated file is stored through the existing
Artifact Service so `app.artifacts` records its purpose, media type, generated download name, size and
SHA-256 without a new schema or migration.

The controlled `GET /artifacts/{artifactId}/download` route first resolves metadata, permits only
`forecast_export`, `metrics`, `chart` and `manifest`, then streams by artifact ID. API models never
return `storage_key` or filesystem paths. Attachment filenames remove path separators, control
characters and header metacharacters. Missing/deleted metadata maps to 404 Problem Details, a wrong
purpose to 403, and metadata whose bytes are unavailable to 410. Failed experiments return 409 when
an export is requested.

CSV serialization has explicit UTF-8 encoding and constant field sequences. Text cells beginning
with `=`, `+`, `-` or `@` (including after leading whitespace) are prefixed with an apostrophe before
CSV quoting so spreadsheet applications treat them as literal values. Numeric values are not
rewritten.

No dependency version changed in TASK-16. Before the pull-request gate, the prepared TASK-16 Python
files passed `python -m py_compile`; the earlier isolated export unit harness passed 10 tests with 0
failures and 0 skips. Repository-wide `ruff`, formatting, mypy, PostgreSQL integration, Alembic,
frontend, Compose and full verification results are intentionally left to the pull-request CI gate
and are not claimed as passing in this entry before that gate completes.

ADR-024 records immediate bounded artifact-backed exports and purpose-controlled downloads. No DDL
or Alembic migration change is required because the existing artifact purpose values and metadata
columns already cover all TASK-16 export formats. TASK-17 has not been started.
'''
new = '''## TASK-16 — Exports and controlled downloads

**Date:** 2026-08-07
**Status:** implemented and repository-wide CI verified

Implemented the bounded export boundary on top of the existing forecast, experiment and Artifact
services. Forecast results serialize to fixed-column UTF-8 CSV or chart-ready JSON. Completed
experiments serialize persisted comparison metrics to normalized CSV or structured JSON and expose
the canonical persisted result manifest as JSON. Every generated file is stored through the existing
Artifact Service so `app.artifacts` records its purpose, media type, generated download name, size and
SHA-256 without a new schema or migration.

The controlled `GET /artifacts/{artifactId}/download` route first resolves metadata, permits only
`forecast_export`, `metrics`, `chart` and `manifest`, then streams by artifact ID. API models never
return `storage_key` or filesystem paths. Attachment filenames remove path separators, control
characters and header metacharacters. Missing/deleted metadata maps to 404 Problem Details, a wrong
purpose to 403, and metadata whose bytes are unavailable to 410. Failed experiments return 409 when
an export is requested.

CSV serialization has explicit UTF-8 encoding and constant field sequences. Text cells beginning
with `=`, `+`, `-` or `@` (including after leading whitespace) are prefixed with an apostrophe before
CSV quoting so spreadsheet applications treat them as literal values. Numeric values are not
rewritten.

No dependency version changed in TASK-16. Before the pull-request gate, the prepared TASK-16 Python
files passed `python -m py_compile`; the earlier isolated export unit harness passed 10 tests with 0
failures and 0 skips.

### Repository-wide verification evidence

TASK-16 PR #15 ran Baseline CI on head `03ff1e761f20d2c101747d735f330eae23f8442e`
(run 32) with both Backend and Frontend jobs successful. After squash merge, `main` commit
`f72cfa74407d8c23e2f17334cbf958042b92c077` ran Baseline CI on push (run 33); both jobs completed
successfully again.

| CI job | Command / gate | Actual result on post-merge `main` |
|---|---|---|
| Backend | `uv sync --all-groups --frozen` | exit 0; 45 locked packages installed |
| Backend | `uv run --frozen ruff check .` | exit 0; all checks passed |
| Backend | `uv run --frozen ruff format --check .` | exit 0; 131 files already formatted |
| Backend | `uv run --frozen mypy src tests` | exit 0; no issues in 127 source files |
| Backend | `uv run --frozen alembic upgrade head` | exit 0; migrations applied through `c3d9a5f27410` |
| Backend | `uv run --frozen alembic check` | exit 0; `No new upgrade operations detected.` |
| Backend | `uv run --frozen pytest -m "not performance"` | exit 0; 187 collected, 2 deselected, 185 passed, 0 failed, 0 skipped in 59.39 s |
| Frontend | `npm ci` | exit 0; 275 packages added, 276 audited, 0 vulnerabilities |
| Frontend | `npm run lint` | exit 0; no ESLint errors |
| Frontend | `npm run typecheck` | exit 0; no TypeScript errors |
| Frontend | `npm run test -- --run` | exit 0; 1 file, 1 test passed, 0 failed |
| Frontend | `npm run build` | exit 0; 29 modules transformed; 193.98 kB JS bundle (61.16 kB gzip) |

The complete backend run includes 12 export-specific unit/integration tests across export
serialization, service and API files. The post-merge run therefore closes the repository-wide
verification item that was intentionally pending in the original TASK-16 log entry.

ADR-024 records immediate bounded artifact-backed exports and purpose-controlled downloads. No DDL
or Alembic migration change is required because the existing artifact purpose values and metadata
columns already cover all TASK-16 export formats. TASK-17 has not been started.
'''
if old in text:
    path.write_text(text.replace(old, new), encoding="utf-8")
elif new not in text:
    raise SystemExit("TASK-16 log block did not match expected baseline")
