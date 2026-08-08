#!/usr/bin/env python3
"""Fetch reproducible Point-5 weather-ablation inputs from Open-Meteo.

This is research evidence, not an operational weather forecast. The requested
coordinate is the GeoNames centre of Sceaux, France, because the UCI dataset does
not publish the household's exact coordinates.

Open-Meteo documents temperature and humidity as native ERA5-Land variables,
while precipitation and 10-m wind for the ERA5-Land product are supplied from
ERA5 forcing. Requesting all fields under ``models=era5_land`` can therefore
produce missing forcing values. To keep W1 deterministic and free of hidden
interpolation, this script explicitly requests the native fields from ERA5-Land
and the forcing fields from ERA5, verifies exact hourly alignment, and derives
apparent temperature consistently for every row.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

LATITUDE = 48.776442
LONGITUDE = 2.290258
GEOCODING_SOURCE = "GeoNames Sceaux populated-place centre"
GEOCODING_SOURCE_URL = "https://www.geonames.org/search.html?country=FR&q=Sceaux"
API_BASE = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_HISTORICAL_DOCS = "https://open-meteo.com/en/docs/historical-weather-api"
ERA5_LAND_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
)
ERA5_FORCING_VARIABLES = (
    "precipitation",
    "wind_speed_10m",
)
OUTPUT_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "precipitation",
    "wind_speed_10m",
)
APPARENT_TEMPERATURE_REFERENCE = "https://doi.org/10.1371/journal.pone.0025101"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _apparent_temperature_celsius(
    temperature_c: float,
    relative_humidity_percent: float,
    wind_speed_kmh: float,
) -> float:
    """Return Steadman non-radiative apparent temperature in degrees Celsius."""

    vapour_pressure_hpa = (
        relative_humidity_percent
        / 100.0
        * 6.105
        * math.exp(17.27 * temperature_c / (237.7 + temperature_c))
    )
    wind_speed_ms = wind_speed_kmh / 3.6
    return temperature_c + 0.33 * vapour_pressure_hpa - 0.70 * wind_speed_ms - 4.0


def _request_parameters(
    *,
    model: str,
    variables: tuple[str, ...],
    start_date: str,
    end_date: str,
) -> dict[str, str]:
    return {
        "latitude": f"{LATITUDE:.6f}",
        "longitude": f"{LONGITUDE:.6f}",
        "start_date": start_date,
        "end_date": end_date,
        "hourly": ",".join(variables),
        "models": model,
        "timezone": "UTC",
        "cell_selection": "land",
    }


def _fetch(params: dict[str, str]) -> dict[str, Any]:
    url = f"{API_BASE}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": "EnergyForecast-coursework-point5/1.0"})
    with urlopen(request, timeout=120) as response:  # noqa: S310 - fixed HTTPS endpoint
        if response.status != 200:
            raise SystemExit(f"Open-Meteo returned HTTP {response.status}")
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("Open-Meteo response is not a JSON object")
    return payload


def _validated_columns(
    payload: dict[str, Any],
    variables: tuple[str, ...],
    *,
    source_label: str,
) -> tuple[list[str], dict[str, list[float]]]:
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        raise SystemExit(f"{source_label} response is missing hourly data")
    times = hourly.get("time")
    if not isinstance(times, list) or not times or not all(isinstance(value, str) for value in times):
        raise SystemExit(f"{source_label} response contains no valid hourly timestamps")

    columns: dict[str, list[float]] = {}
    for variable in variables:
        values = hourly.get(variable)
        if not isinstance(values, list) or len(values) != len(times):
            raise SystemExit(f"{source_label} variable {variable} is missing or misaligned")
        if any(value is None for value in values):
            raise SystemExit(f"{source_label} variable {variable} contains missing values")
        try:
            numeric = [float(value) for value in values]
        except (TypeError, ValueError) as exc:
            raise SystemExit(f"{source_label} variable {variable} is non-numeric") from exc
        if not all(math.isfinite(value) for value in numeric):
            raise SystemExit(f"{source_label} variable {variable} contains non-finite values")
        columns[variable] = numeric
    return times, columns


def _returned_grid(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "latitude": payload.get("latitude"),
        "longitude": payload.get("longitude"),
        "elevation": payload.get("elevation"),
        "timezone": payload.get("timezone"),
        "utc_offset_seconds": payload.get("utc_offset_seconds"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default="2006-12-16")
    parser.add_argument("--end-date", default="2010-11-28")
    parser.add_argument("--csv-output", type=Path, required=True)
    parser.add_argument("--metadata-output", type=Path, required=True)
    args = parser.parse_args()

    era5_land_params = _request_parameters(
        model="era5_land",
        variables=ERA5_LAND_VARIABLES,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    era5_params = _request_parameters(
        model="era5",
        variables=ERA5_FORCING_VARIABLES,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    era5_land_payload = _fetch(era5_land_params)
    era5_payload = _fetch(era5_params)

    land_times, land_columns = _validated_columns(
        era5_land_payload,
        ERA5_LAND_VARIABLES,
        source_label="Open-Meteo ERA5-Land",
    )
    forcing_times, forcing_columns = _validated_columns(
        era5_payload,
        ERA5_FORCING_VARIABLES,
        source_label="Open-Meteo ERA5",
    )
    if land_times != forcing_times:
        raise SystemExit("ERA5-Land and ERA5 timestamps are not exactly aligned")

    apparent_temperature = [
        _apparent_temperature_celsius(temperature, humidity, wind_speed)
        for temperature, humidity, wind_speed in zip(
            land_columns["temperature_2m"],
            land_columns["relative_humidity_2m"],
            forcing_columns["wind_speed_10m"],
            strict=True,
        )
    ]
    columns: dict[str, list[float]] = {
        "temperature_2m": land_columns["temperature_2m"],
        "relative_humidity_2m": land_columns["relative_humidity_2m"],
        "apparent_temperature": apparent_temperature,
        "precipitation": forcing_columns["precipitation"],
        "wind_speed_10m": forcing_columns["wind_speed_10m"],
    }

    csv_output = args.csv_output.resolve()
    csv_output.parent.mkdir(parents=True, exist_ok=True)
    with csv_output.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.writer(destination)
        writer.writerow(("timestamp", *OUTPUT_VARIABLES))
        for index, timestamp in enumerate(land_times):
            writer.writerow((timestamp, *(columns[name][index] for name in OUTPUT_VARIABLES)))

    metadata = {
        "schema": "energyforecast-point5-weather/v2",
        "research_mode": "W1_idealized_reanalysis",
        "operational_forecast_claim": False,
        "provider": "Open-Meteo Historical Weather API",
        "reanalysis_model": "ERA5-Land + ERA5 forcing",
        "api_endpoint": API_BASE,
        "documentation": OPEN_METEO_HISTORICAL_DOCS,
        "request_parameters": {
            "era5_land": era5_land_params,
            "era5": era5_params,
        },
        "requested_location": {
            "name": "Sceaux, Hauts-de-Seine, France",
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "coordinate_semantics": "approximate city centre; exact UCI household coordinates are unpublished",
            "geocoding_source": GEOCODING_SOURCE,
            "geocoding_source_url": GEOCODING_SOURCE_URL,
        },
        "returned_grid": {
            "era5_land": _returned_grid(era5_land_payload),
            "era5": _returned_grid(era5_payload),
        },
        "source_variable_mapping": {
            "temperature_2m": "ERA5-Land",
            "relative_humidity_2m": "ERA5-Land",
            "precipitation": "ERA5 forcing",
            "wind_speed_10m": "ERA5 forcing",
            "apparent_temperature": "derived from ERA5-Land temperature/humidity and ERA5 wind",
        },
        "hourly_variables": list(OUTPUT_VARIABLES),
        "derived_variables": {
            "apparent_temperature": {
                "method": "Steadman non-radiative apparent temperature",
                "formula": "AT = Ta + 0.33*e - 0.70*ws - 4.00; e = RH/100*6.105*exp(17.27*Ta/(237.7+Ta))",
                "temperature_unit": "degC",
                "relative_humidity_unit": "percent",
                "input_wind_unit": "km/h",
                "formula_wind_unit": "m/s",
                "solar_radiation_included": False,
                "reference": APPARENT_TEMPERATURE_REFERENCE,
                "reason": "derive one complete, deterministic definition for all hours rather than interpolate missing convenience values",
            }
        },
        "weather_missing_value_policy": "fail_on_missing_source_variable; no interpolation",
        "source_rationale": "Open-Meteo documents ERA5-Land precipitation and wind as ERA5 forcing variables; they are fetched explicitly from ERA5 to avoid missing convenience fields while preserving the documented data lineage.",
        "hourly_rows": len(land_times),
        "first_timestamp": land_times[0],
        "last_timestamp": land_times[-1],
        "csv_sha256": _sha256(csv_output),
    }
    metadata_output = args.metadata_output.resolve()
    metadata_output.parent.mkdir(parents=True, exist_ok=True)
    metadata_output.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
