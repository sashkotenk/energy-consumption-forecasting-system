# EnergyForecast testing strategy

EnergyForecast uses a layered test pyramid so that domain rules, persistence behavior, HTTP
contracts, React workflows, deployment wiring and the primary browser journey fail close to the layer
that owns the defect.

## Pull request and main gates

The main verification workflow keeps concerns independent so the failing owner is visible immediately:

- backend Ruff lint and format check;
- strict backend mypy;
- backend unit tests;
- PostgreSQL/TimescaleDB integration tests on a real service;
- Alembic upgrade and migration-drift check;
- dedicated `ml_guard` leakage/reproducibility regression tests;
- full backend coverage run for critical data/ML/application packages;
- runtime OpenAPI, design/runtime assertions and generated TypeScript SDK drift;
- frontend ESLint, TypeScript, Vitest/React Testing Library and production build;
- Playwright Chromium primary synthetic journey;
- hardened Docker image build plus clean-volume six-service Compose smoke;
- Gitleaks history/private-file scan, Python/npm dependency audit and container vulnerability scan;
- repository-wide `scripts/verify.ps1`, workflow YAML parsing and `git diff --check`.

TASK-22 adds a separate pull-request **Release Evidence** workflow. It verifies documentation
links/Mermaid sources, runs a deterministic release benchmark plus the `performance` marker, captures
a screenshot from the successful Playwright primary flow and uploads benchmark/browser evidence for
review. Committed evidence is checksum-verified by `scripts/verify_evidence.py`.

The workflows use repository read-only permissions and do not require application secrets for pull
requests. Production-like Compose configuration fails fast when deployment credentials and immutable
commit metadata are omitted.

## Deterministic synthetic fixtures

`backend/tests/fixtures/synthetic.py` centralizes small fixtures for the regression cases required by
the forecasting protocol:

- invalid timestamp;
- conflicting duplicate;
- bounded five-minute and non-interpolated six-minute gaps;
- zero demand;
- exact daily seasonality;
- DST-like repeated local clock hour;
- spreadsheet formula prefixes in CSV text.

No fixture depends on a developer-machine path, execution order or wall-clock time.

## Mandatory ML guards

All time-series leakage and reproducibility guards use `pytest.mark.ml_guard`. They protect
deterministic feature schemas, the first 168-hour lag boundary, 24 direct targets, shifted rolling
statistics, future-target isolation, missing-hour handling, local calendar cycles, past-only quality
features, four expanding validation folds, the 24-hour purge, final-test isolation and train-only
preprocessing.

Run only the guards from `backend`:

```text
uv run --frozen pytest -m ml_guard
```

The normal backend verification also includes these tests; the dedicated job makes regression count
and failure ownership explicit.

## Database and migration verification

Integration jobs use the same pinned TimescaleDB/PostgreSQL major baseline as Docker Compose. The
migration gate executes `alembic upgrade head` and `alembic check`; repository verification repeats
those checks against the development database. The release migration head is `c3d9a5f27410`. TASK-22
changes no schema, so no migration is added merely to create activity.

## Browser E2E and screenshot evidence

From `frontend`, after installing the locked dependencies and Chromium:

```text
npm ci
npx playwright install --with-deps chromium
npm run e2e
```

The primary scenario covers:

```text
import -> quality/transform -> analysis -> experiment -> comparison -> forecast -> CSV export
```

Playwright uses explicit UI assertions and application terminal states rather than arbitrary sleeps.
In CI, successful runs also capture a browser screenshot into `test-results`; the Release Evidence
workflow uploads that directory so representative UI evidence can be copied into the public evidence
pack from a verified run.

## Container and Compose smoke

`python scripts/verify_infrastructure.py` checks the static deployment contract: the exact six
services, pinned images, migration/health dependencies, network isolation, production absence of bind
mounts/database ports, read-only roots, 300 MiB upload alignment, controlled artifact boundary and
private-file exclusion.

`bash scripts/compose-smoke.sh` creates a unique Compose project with clean volumes, builds the images,
uses Compose health-state waiting, checks the SPA and `/api/v1/health/ready`, verifies the migration
container exit code, and always destroys the temporary project. It does not use fixed sleeps.

Together with the deterministic Playwright primary journey, this provides the clean-deployment and
end-to-end release gates without coupling browser correctness to a large external UCI fixture.

## Security and dependency scans

Pull requests and `main` run:

- Gitleaks against Git history with redacted output;
- a tracked-path guard against private planning/specification material;
- `pip-audit` against the exported locked production Python requirements;
- `npm audit --audit-level=high` against the locked frontend graph;
- Trivy high/critical, fixed-vulnerability checks for backend, web and edge images.

A reported vulnerability is treated as a real dependency/container defect to investigate; checks are
not bypassed by suppressing assertions solely to obtain green CI. The release-specific trust-boundary
review is stored in `docs/evidence/security-review.md`.

## Performance evidence

The ordinary `performance` marker keeps parser incremental memory bounded. TASK-22 also provides:

```text
cd backend
uv run --frozen python ../scripts/generate_release_benchmark.py --output ../build/release-benchmark.json
uv run --frozen pytest -m performance
```

The deterministic benchmark records runner CPU/memory/Python profile and measured parser, quality,
transformation, bounded-analytics, FastAPI liveness and direct-24 Ridge train/predict timings. Model
training uses a warmup followed by three measured fits; prediction records median and p95 across 30
repetitions. The synthetic benchmark is engineering evidence, not a substitute for the final UCI
scientific experiment.

The nightly schedule additionally runs the deterministic performance marker and a focused classical-ML
fixture suite.

## Full UCI profile

The complete UCI Individual Household Electric Power Consumption file is deliberately not stored in
the repository and is excluded from normal PR CI. A manual profile can stream the external source
without copying it into Git:

```text
ENERGYFORECAST_UCI_PATH=<path-to-household_power_consumption.txt>
./scripts/run_uci_profile.ps1
```

On PowerShell set the environment variable with `$env:ENERGYFORECAST_UCI_PATH` before running the
script. The profile is marked `full_dataset`; normal verification selects
`not performance and not full_dataset`.

## Documentation and evidence integrity

Run from the repository root:

```text
python scripts/verify_documentation.py
python scripts/verify_evidence.py
```

The first command checks repository-local Markdown targets and Mermaid source structure. The second
recomputes SHA-256 values from `docs/evidence/handoff-manifest.json`. Both run from the final
repository-wide verification gate once the evidence manifest exists.

## Coverage policy

Coverage is diagnostic evidence, not a reason to relax assertions, tolerances, leakage guards or
error handling. The CI report focuses on critical domain and application packages. A missing line
should lead to a meaningful test only when the behavior is relevant; no production branch is excluded
or weakened solely to increase a percentage.

Exact execution counts, coverage, benchmark measurements and CI run evidence are recorded in
`docs/implementation-log.md` and `docs/evidence/verification.md`.
