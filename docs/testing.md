# EnergyForecast testing strategy

EnergyForecast uses a layered test pyramid so that domain rules, persistence behavior, HTTP contracts, React workflows and the primary browser journey fail close to the layer that owns the defect.

## Pull request gates

The baseline workflow runs the following independent gates:

- backend lint, formatting and strict mypy;
- runtime OpenAPI drift and Alembic drift checks;
- the dedicated `ml_guard` marker plus the complete backend suite against a real PostgreSQL/TimescaleDB service;
- a coverage report focused on data ingestion, quality, transformations, ML, experiments, forecasting and exports;
- frontend generated-SDK drift, lint, typecheck, Vitest/React Testing Library and production build;
- Playwright Chromium coverage of the primary synthetic product journey;
- repository-wide `scripts/verify.ps1` and `git diff --check`.

The browser test uses contract-shaped deterministic API responses to exercise routing, form state, polling termination, charts, comparison, forecast creation and controlled download behavior in the browser. Real database, API, worker, artifact and migration behavior is covered independently by backend integration tests using temporary TimescaleDB databases. This separation keeps browser tests deterministic while preserving real persistence coverage.

## Deterministic synthetic fixtures

`backend/tests/fixtures/synthetic.py` centralizes small fixtures for the regression cases required by the forecasting protocol:

- invalid timestamp;
- conflicting duplicate;
- bounded five-minute and non-interpolated six-minute gaps;
- zero demand;
- exact daily seasonality;
- DST-like repeated local clock hour;
- spreadsheet formula prefixes in CSV text.

No fixture depends on a developer-machine path, execution order or wall-clock time.

## Mandatory ML guards

All time-series leakage and reproducibility guards use `pytest.mark.ml_guard`. They protect deterministic feature schemas, the first 168-hour lag boundary, 24 direct targets, shifted rolling statistics, future-target isolation, missing-hour handling, local calendar cycles, past-only quality features, four expanding validation folds, the 24-hour purge, final-test isolation and train-only preprocessing.

Run only the guards from `backend`:

```text
uv run --frozen pytest -m ml_guard
```

The normal PR backend suite also includes these tests.

## Browser E2E

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

## Full UCI profile

The complete UCI Individual Household Electric Power Consumption file is deliberately not stored in the repository and is excluded from normal PR CI. A manual or scheduled profile can stream the external source without copying it into Git:

```text
ENERGYFORECAST_UCI_PATH=<path-to-household_power_consumption.txt>
./scripts/run_uci_profile.ps1
```

On PowerShell set the environment variable with `$env:ENERGYFORECAST_UCI_PATH` before running the script. The profile is marked `full_dataset`; normal verification selects `not performance and not full_dataset`.

## Coverage policy

Coverage is diagnostic evidence, not a reason to relax assertions, tolerances, leakage guards or error handling. The CI report focuses on critical domain and application packages. A missing line should lead to a meaningful test only when the behavior is relevant; no production branch is excluded or weakened solely to increase a percentage.

Exact TASK-20 execution counts, coverage and CI run evidence are recorded in `docs/implementation-log.md`.
