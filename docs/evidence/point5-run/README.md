# Point 5 — final ML study evidence

This directory is generated from the full external UCI *Individual Household Electric Power Consumption* source and the frozen EnergyForecast release candidate `35a4a3afe013dbe0d1098d3723a2f20047f163f4`.

## Dataset and protocol

- UCI SHA-256: `4259c9d7ece5dbee9ab8d53682baac68d791c864f0f64a52b4043cb3b90894b7`
- prepared hourly dataset version: `69db3a8a-4163-4bdf-a435-4a72eafc148d`
- hourly rows: 34589
- feature schema: `base_v1` / `e58c9eb93e8ce16823bb4c5010346818b78850ff6825c48d287dc6a884151e9d`
- split: `uci_2009_quarters_2010_test_v1` with four chronological 2009 validation folds and a 24-hour purge
- final test: 2010, opened only after `selection-decision.json` was fsync-persisted
- tree-model search: 4 deterministic sampled configurations per tree family; Ridge uses its complete six-alpha grid

## Selected W0 model

The formal pre-test rule selected **random_forest** (E11) with mean CV MAE **0.456281 kWh** and CV standard deviation **0.056815 kWh**.

On the isolated 2010 final test (6475 eligible hourly origins):

- selected W0 MAE: **0.438996 kWh**
- selected W0 RMSE: **0.602644 kWh**
- selected W0 sMAPE: **44.025%**
- Seasonal Naive-24 MAE: **0.555039 kWh**
- MAE improvement relative to Seasonal Naive-24: **20.907%**
- paired 168-origin moving-block bootstrap 95% interval for `MAE_selected - MAE_baseline`: **[-0.142039, -0.083578] kWh**
- stable improvement under the predefined bootstrap rule: **True**

The working ML-superiority hypothesis is **supported for the preselected W0 candidate**. No model, feature, threshold, or hyperparameter was changed after the 2010 indexes were opened.

## Weather ablation

W1 uses ERA5-Land reanalysis from Open-Meteo at the GeoNames centre of Sceaux (`48.776442, 2.290258`). Exact household coordinates are not published by UCI. W1 supplies the reanalysis value at `t+h` to the horizon-`h` regressor, so it is an **idealized upper-bound experiment**, not an operational weather forecast.

For the selected W0 algorithm family, final W1 MAE is **0.439562 kWh** versus W0 **0.438996 kWh**.

## Computational evidence

- median final training time after one warm-up: **1102.231 s**
- 24-hour prediction median / p95 over 30 measured runs: **392.552 / 411.777 ms**
- serialized selected `joblib`: **505263668 bytes**
- verified internal model bundle: `25ed1785-2a05-4ffa-9583-2048b05d0a3c` / `1df88895054f8ff477eb9f9aa70ae6656a1231a49f600c3825fa862f678fd551`
- final product-path forecast contains exactly 24 ordered points and total energy `31.472638 kWh`

## Files

- `point5-handoff.json` — bound UCI SHA/UUID handoff;
- `dataset-preparation.json` — import/transformation and quality counts;
- `selection-decision.json` — immutable pre-final-test recommendation;
- `search-results.csv`, `fold-results.csv` — tuning and chronological validation evidence;
- `final-results.csv`, `horizon-results.csv`, `final-predictions.csv` — machine-readable scientific results;
- `bootstrap.json` — paired moving-block uncertainty;
- `benchmark.json` — training/prediction/feature timing and sizes;
- `weather-metadata.json` — W1 source, coordinates and checksum;
- `product-forecast.json` — verified-bundle 24-hour final scenario;
- `actual-vs-forecast.svg`, `mae-by-horizon.svg`, `cv-model-comparison.svg` — report-ready graphics;
- `run-manifest.json` — top-level provenance and conclusions.

## Threats to validity

1. The UCI household timezone is not formally published; EnergyForecast uses the predefined `Europe/Paris` interpretation and records DST/duplicate effects through the quality pipeline.
2. Exact household coordinates are unavailable; W1 uses the documented Sceaux city-centre proxy.
3. ERA5-Land is reanalysis. Future `t+h` weather is therefore privileged information and cannot be presented as operational forecast accuracy.
4. This is a single household, so external validity to other buildings or grids is limited.
5. Forecast origins overlap. The uncertainty analysis therefore resamples consecutive 168-origin blocks instead of treating hourly errors as independent.
6. Runtime measurements describe the recorded GitHub Actions runner and pinned single-thread scientific profile; they are not universal hardware benchmarks.
7. Tree-model search is deliberately bounded for CPU-only reproducibility; the exact sampled configurations are preserved in `search-results.csv`.

## Execution acceleration

Cross-validation fitted the 24 independent direct horizons with **2 parallel jobs** using a shared-memory thread backend to stay within hosted-runner RAM limits. This changes execution scheduling only: candidate grids, chronological folds, purge, random seed, targets, metrics and the selection rule are unchanged. Prediction timing used for tie-breaking and the final three-repeat benchmark remain single-threaded.
