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

The separate pull-request **Release Evidence** workflow verifies documentation links/Mermaid sources
and the deterministic demo-data generator, runs the deterministic release benchmark, executes both
`performance` tests against a real pinned TimescaleDB service, records the production frontend bundle,
captures the successful Playwright primary flow and uploads benchmark/browser evidence for review.
Committed TASK-22 handoff evidence remains checksum-verified by `scripts/verify_evidence.py`.

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

`scripts/generate_demo_dataset.py` separately produces a deterministic hourly `timestamp,energy_kwh`
CSV for clean product demonstrations without committing or downloading the UCI dataset. The default
120-day profile is long enough for the lagged forecasting workflow and is explicitly engineering/demo
data rather than scientific evidence.

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
those checks against the development database. The release migration head is `c3d9a5f27410`. The
release-polish audit changes no schema and therefore adds no migration merely to create activity.

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
workflow uploads that directory so representative UI evidence can be reviewed from a verified run.

## Container and Compose smoke

`python scripts/verify_infrastructure.py` checks the static deployment contract: the exact six
services, pinned images, migration/health dependencies, network isolation, production absence of bind
mounts/database ports, read-only roots, 300 MiB upload alignment, controlled artifact boundary,
private-file exclusion and consistency of `.env.example` with the actual Compose/runtime setting
names and local defaults.

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

The Release Evidence benchmark is executed through the locked backend environment:

```text
cd backend
uv run --frozen python ../scripts/generate_release_benchmark.py --output ../build/release-benchmark.json
uv run --frozen pytest -m performance
```

The deterministic benchmark records the runner CPU/memory/Python profile, streaming parser throughput
and peak incremental memory, quality timing, minute-to-hour transformation timing, combined daily
quality-plus-transformation timing, bounded-analytics selection, FastAPI liveness, and direct-24
training/prediction/artifact-size measurements for Ridge, Random Forest and Histogram Gradient
Boosting. Model benchmarks use fixed seed/data and one-thread model parallelism; prediction records
median and p95. The synthetic benchmark is engineering evidence, not a substitute for the final UCI
scientific experiment.

The `performance` marker contains the parser memory regression and a real PostgreSQL/TimescaleDB
maximum-range analytics regression. Release Evidence now provisions the pinned database and supplies
`TEST_DATABASE_URL`, so neither case is intentionally skipped there. The ordinary CI still keeps these
slower checks out of unit/integration jobs by marker selection while the release evidence workflow
executes them explicitly.

The production frontend build is also executed in Release Evidence. ECharts imports only the required
chart/component modules and Vite splits framework, charts, rendering and form dependencies into
bounded production chunks instead of retaining the previous single >500 kB minified JavaScript chunk.

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

Exact historical TASK-22 execution counts, coverage and committed handoff measurements remain in
`docs/implementation-log.md` and `docs/evidence/verification.md`; subsequent release-polish runs are
visible in GitHub Actions and do not rewrite checksum-locked historical evidence.
