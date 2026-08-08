# EnergyForecast user guide

EnergyForecast is a single-user web application for importing electricity-consumption time series, reviewing data quality, creating immutable hourly versions, analysing consumption, comparing forecasting methods and producing a direct 24-hour forecast.

## 1. Start the application

For local development from the repository root:

```bash
docker compose up --build
```

The browser UI is served at `http://localhost:5173`. The production-like topology and edge-proxy entry point are documented in [deployment.md](deployment.md).

## 2. Import a dataset

Open **Datasets** and choose **New import**. Two import profiles are supported:

- **UCI household power** for the UCI Individual Household Electric Power Consumption text format;
- **generic CSV** for a compatible timestamp plus `energy_kwh` or `active_power_kw` source.

For a generic CSV, select the timestamp column, target quantity, delimiter/decimal semantics and timezone context. The uploaded filename is metadata only; storage keys are generated internally. The UI polls the import job until a terminal state and then links to the immutable imported dataset version.

The full UCI file is not stored in this repository. It must be supplied by the user when an external full-dataset profile is required.

## 3. Review data quality

Open **Data quality** for the imported version. The report distinguishes missing measurements from zero demand and reports parse errors, duplicates, time gaps, physically invalid values and statistical anomalies.

Creating an hourly version requires an explicit transformation policy. Short interpolation is bounded to gaps of at most five minutes. Longer gaps are not silently filled or scaled to a full hour. Conflicting duplicates require an explicit duplicate policy.

Every transformation creates a new immutable dataset version; it does not overwrite the raw source or an earlier version.

## 4. Analyse hourly consumption

Open **Analysis** for a ready hourly version. The server returns bounded aggregates for:

- summary statistics;
- energy series;
- hourly and weekday profiles;
- heatmap values;
- distribution bins.

Charts are paired with textual or tabular information. Requests are bounded on the server before rendering.

## 5. Run and compare experiments

Open **Experiments** and create an experiment from a ready hourly version. The supported required algorithms are:

- Seasonal Naive-24;
- Seasonal Naive-168 diagnostic baseline;
- Ridge Regression;
- Random Forest Regressor;
- Histogram Gradient Boosting Regressor.

The implemented W0 mode uses consumption-history and calendar features. W1 remains an explicit unsupported mode until a real weather source is connected; the application does not pretend that future reanalysis values are operational weather forecasts.

Experiments preserve dataset/version provenance, feature schema, parameters, seed, fold/final metrics and model-bundle metadata. Model comparison uses common eligible forecast origins. Selection is completed from chronological validation evidence before the final 2010 test indexes are requested.

## 6. Create a 24-hour forecast

From a completed comparison, choose the recommended completed model run and open **New forecast**. The service verifies the internal model bundle checksum and compatibility before deserialization.

A forecast contains exactly 24 ordered hourly points, a total expected daily energy value, dataset/model/schema provenance and completion metadata. An explicit origin must be timezone-aware and hour-aligned; otherwise the service chooses the latest eligible completed hour.

If required historical lags are missing, the request fails with an actionable error rather than fabricating history.

## 7. Export and download results

Forecast and experiment results can be exported through controlled artifact-backed routes. Supported outputs include forecast CSV/JSON-style chart data and experiment metrics/manifest data as exposed by the UI/API.

Downloads are resolved by artifact ID. Storage paths and storage keys are never returned as public download locations. CSV text cells that could be interpreted as spreadsheet formulas are neutralized while numeric values remain numeric.

## 8. Operational limits

This coursework release intentionally has no authentication or multi-user authorization. Do not expose it directly to untrusted networks without an external authenticated/TLS gateway and an appropriate threat review.

The application accepts uploads up to the configured 300 MiB boundary. PostgreSQL is private in the production-like Compose topology, and model deserialization is restricted to checksum-verified internal bundles.

## 9. Troubleshooting

- **Job stays queued/running:** confirm the worker container is healthy and inspect `docker compose logs worker`.
- **Readiness fails:** inspect database health and `docker compose logs migrate api db`.
- **Forecast history missing:** choose an origin with enough valid historical observations or prepare another hourly version under an appropriate quality policy.
- **Import rejected:** check timestamp parsing, target-column mapping, units and file structure.
- **Controlled download returns 410:** artifact metadata exists but the backing bytes are unavailable; regenerate the export.

For verification commands see [testing.md](testing.md). For deployment and backup/restore guidance see [deployment.md](deployment.md).
