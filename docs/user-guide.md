# EnergyForecast user guide

EnergyForecast is a single-user web application for importing electricity-consumption time series, reviewing data quality, creating immutable hourly versions, analysing consumption, comparing forecasting methods and producing a direct 24-hour forecast.

## 1. Start the application

### Prerequisites

For the supported full-stack local path you need:

- Git;
- Docker Desktop on Windows/macOS, or Docker Engine with Docker Compose v2 on Linux;
- enough free disk space for the pinned container images, PostgreSQL volume and uploaded artifacts.

A local Python or Node.js installation is **not** required for the normal Docker Compose run.

### Fresh clone

From PowerShell, Git Bash or another terminal:

```bash
git clone https://github.com/sashkotenk/energy-consumption-forecasting-system.git
cd energy-consumption-forecasting-system
git switch main
git pull --ff-only origin main
docker compose up -d --build --wait
```

If the installed Compose version does not support `--wait`, use `docker compose up -d --build` and then `docker compose ps` until the services become healthy.

The supported Compose entry point is:

- application: `http://127.0.0.1:8080`;
- readiness check: `http://127.0.0.1:8080/health/ready`;
- proxied API base: `http://127.0.0.1:8080/api/v1`.

Port `5173` is used only when the Vite development server is started directly from `frontend/`; it is not the Docker Compose UI port.

Useful commands:

```bash
docker compose ps
docker compose logs -f api worker nginx
docker compose down
```

`docker compose down -v` additionally deletes the local PostgreSQL and artifact volumes. Use it only when you intentionally want to reset all local application data.

### Updating an existing clone

If the repository is already on your machine and you have no local work to preserve:

```bash
git switch main
git fetch origin
git pull --ff-only origin main
docker compose up -d --build --wait
```

If Git reports local modifications, do not discard them blindly. Commit them, stash them, or review `git status` before pulling.

### Optional environment file

The development Compose override already has safe local defaults. To make the selected settings explicit, copy `.env.example` to `.env` before startup:

PowerShell:

```powershell
Copy-Item .env.example .env
```

Git Bash/Linux/macOS:

```bash
cp .env.example .env
```

Do not commit `.env` files containing real credentials.

## 2. Generate a deterministic demo dataset

The repository intentionally does not contain the full UCI dataset. For a clean demonstration without downloading external data, generate a synthetic 120-day hourly CSV:

```bash
python scripts/generate_demo_dataset.py --output build/demo-energy.csv
```

If Python is not installed locally but Docker is available, run the same generator in a temporary Python container. In PowerShell from the repository root:

```powershell
docker run --rm -v "${PWD}:/work" -w /work python:3.13-alpine python scripts/generate_demo_dataset.py --output build/demo-energy.csv
```

The generated file has deterministic `timestamp,energy_kwh` columns and contains no private or UCI data. In the import wizard select **generic CSV**. The UI switches the profile defaults to energy/kWh/UTC; keep the following mapping:

- delimiter: `,`;
- timestamp column: `timestamp`;
- target column: `energy_kwh`;
- target semantic: energy;
- unit: kWh;
- timezone: UTC;
- duplicate policy: reject.

The default 120-day profile is long enough to exercise the lagged forecasting workflow and is intended for product demonstration and automated/reproducible engineering checks, not for scientific model-quality conclusions.

## 3. Import a dataset

Open **Datasets** and choose **New import**. Two import profiles are supported:

- **UCI household power** for the UCI Individual Household Electric Power Consumption text format. The wizard fixes the source semantic to `Global_active_power` in kW and defaults the timezone to `Europe/Paris`;
- **generic CSV** for a compatible timestamp plus `energy_kwh` or `active_power_kw` source. Selecting this profile starts from energy/kWh/UTC defaults, which can then be changed to match the source.

For a generic CSV, select the timestamp column, target quantity, delimiter/decimal semantics and timezone context. The uploaded filename is metadata only; storage keys are generated internally. The UI polls the import job until a terminal state.

After a successful import the UI deliberately sends the user to **Data quality** rather than encouraging analysis of the immutable raw version. The raw source remains available for provenance, while analysis and experiments are intended to use the prepared hourly version.

The full UCI file is not stored in this repository. It must be supplied by the user when an external full-dataset profile is required.

## 4. Review data quality and prepare an hourly version

Open **Data quality** for the imported version. The report distinguishes missing measurements from zero demand and reports parse errors, duplicates, time gaps, physically invalid values and statistical anomalies.

The **Missing (all channels)** card is an aggregate over all electrical fields checked by the quality engine. For a generic CSV that intentionally contains only `timestamp` plus the target column, optional UCI-style electrical channels can therefore be reported as entirely missing. This does **not** mean the target series is missing. Use the per-column issue table and severity to distinguish absent optional channels from gaps in the target data.

Creating an hourly version requires an explicit transformation policy. Short interpolation is bounded to gaps of at most five minutes. Longer gaps are not silently filled or scaled to a full hour. Conflicting duplicates require an explicit duplicate policy.

Click **Prepare hourly version**. The page now polls the transformation job, shows terminal-aware progress, the job ID and target-version ID, and stops polling when the job reaches a terminal state. Failed, cancelled or stale transformations remain visible and can be retried without manually copying identifiers.

On success the UI automatically opens **Analysis** for the newly created immutable hourly version. When the quality report contains a full-range issue (for example, an optional channel absent for every generic-CSV row), that known source range is also carried into the analysis URL so demo data outside the historical UCI dates opens on a useful period immediately. Every transformation creates a new immutable dataset version; it never overwrites the raw source or an earlier version.

## 5. Analyse hourly consumption

Open **Analysis** for a ready hourly version. The server returns bounded aggregates for:

- summary statistics;
- energy series;
- hourly and weekday profiles;
- heatmap values;
- distribution bins.

Charts are paired with textual or tabular information. Requests are bounded on the server before rendering. The date controls remain editable, so a different period can be selected at any time.

When the prepared series looks correct, choose **New experiment** from the Analysis page. The hourly dataset-version ID is carried into the experiment builder automatically; there is no need to copy the UUID manually.

## 6. Run and compare experiments

Open **Experiments** and create an experiment from a ready hourly version, or continue directly from **Analysis → New experiment**. The supported required algorithms are:

- Seasonal Naive-24;
- Seasonal Naive-168 diagnostic baseline;
- Ridge Regression;
- Random Forest Regressor;
- Histogram Gradient Boosting Regressor.

The implemented W0 mode uses consumption-history and calendar features. W1 remains an explicit unsupported research extension until a real weather source is connected; the application does not fabricate weather-benefit results or treat future reanalysis data as an operational forecast.

Experiments preserve dataset/version provenance, feature schema, parameters, seed, fold/final metrics and model-bundle metadata. Model comparison uses common eligible forecast origins. Selection is completed from chronological validation evidence before the final 2010 test indexes are requested.

## 7. Create a 24-hour forecast

From a completed comparison, choose the recommended completed model run and open **New forecast**. The service verifies the internal model bundle checksum and compatibility before deserialization.

A forecast contains exactly 24 ordered hourly points, a total expected daily energy value, dataset/model/schema provenance and completion metadata. An explicit origin must be timezone-aware and hour-aligned; otherwise the service chooses the latest eligible completed hour.

If required historical lags are missing, the request fails with an actionable error rather than fabricating history.

## 8. Export and download results

Forecast and experiment results can be exported through controlled artifact-backed routes. Supported outputs include forecast CSV/JSON-style chart data and experiment metrics/manifest data as exposed by the UI/API.

Downloads are resolved by artifact ID. Storage paths and storage keys are never returned as public download locations. CSV text cells that could be interpreted as spreadsheet formulas are neutralized while numeric values remain numeric.

## 9. Operational limits and supported boundary

This coursework release intentionally has no built-in authentication or multi-user authorization. This is a documented scope decision, not a missing local-start dependency. Do not expose the application directly to an untrusted network without an external authenticated/TLS gateway and an appropriate threat review.

The application accepts uploads up to the configured 300 MiB boundary. PostgreSQL is private in the production-like Compose topology, and model deserialization is restricted to checksum-verified internal bundles.

W1 weather features and final scientific claims on the complete UCI dataset remain outside the implemented operational baseline. W0 forecasting, deterministic synthetic evidence and an externally supplied UCI run are the supported paths.

## 10. Troubleshooting

- **Port 8080 is already in use:** set `APP_HTTP_PORT` in `.env`, for example `APP_HTTP_PORT=18080`, then restart Compose and open the selected port.
- **Port 5432 is already in use in the development override:** stop the conflicting local database or change the development DB port according to [deployment.md](deployment.md).
- **Docker cannot start containers:** verify Docker Desktop/Engine is running with `docker version` and `docker compose version`.
- **Job stays queued/running:** confirm the worker container is healthy and inspect `docker compose logs worker`.
- **Readiness fails:** inspect database health and `docker compose logs migrate api db`.
- **Hourly preparation fails:** read the terminal-state error on the Data quality page and use **Retry transformation** after correcting the underlying data/worker issue.
- **Forecast history missing:** choose an origin with enough valid historical observations or prepare another hourly version under an appropriate quality policy.
- **Import rejected:** check timestamp parsing, target-column mapping, units and file structure.
- **Controlled download returns 410:** artifact metadata exists but the backing bytes are unavailable; regenerate the export.

For verification commands see [testing.md](testing.md). For deployment and backup/restore guidance see [deployment.md](deployment.md).
