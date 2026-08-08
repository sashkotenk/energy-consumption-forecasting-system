#!/usr/bin/env python3
"""Fetch the Point-5 ERA5-Land weather ablation input from Open-Meteo.

This is research evidence, not an operational weather forecast. The requested
coordinate is the GeoNames centre of Sceaux, France, because the UCI dataset does
not publish the household's exact coordinates.

Open-Meteo's ERA5-Land response can expose gaps in the convenience
``apparent_temperature`` field even when the underlying temperature, humidity and
wind fields are present. To keep the W1 ablation deterministic and free of hidden
weather interpolation, this script requests only complete source meteorological
variables and derives apparent temperature for every hour with the documented
Steadman non-radiative formula.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

LATITUDE = 48.776442
LONGITUDE = 2.290258
GEOCODING_SOURCE = "GeoNames Sceaux populated-place centre"
GEOCODING_SOURCE_URL = "https://www.geonames.org/search.html?country=FR&q=Sceaux"
API_BASE = "https://archive-api.open-meteo.com/v1/archive"
SOURCE_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default="2006-12-16")
    parser.add_argument("--end-date", default="2010-11-28")
    parser.add_argument("--csv-output", type=Path, required=True)
    parser.add_argument("--metadata-output", type=Path, required=True)
    args = parser.parse_args()

    params = {
        "latitude": f"{LATITUDE:.6f}",
        "longitude": f"{LONGITUDE:.6f}",
        "start_date": args.start_date,
        "end_date": args.end_date,
        "hourly": ",".join(SOURCE_VARIABLES),
        "models": "era5_land",
        "timezone": "UTC",
        "cell_selection": "land",
    }
    url = f"{API_BASE}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": "EnergyForecast-coursework-point5/1.0"})
    with urlopen(request, timeout=120) as response:  # noqa: S310 - fixed HTTPS endpoint
        if response.status != 200:
            raise SystemExit(f"Open-Meteo returned HTTP {response.status}")
        payload = json.loads(response.read().decode("utf-8"))

    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        raise SystemExit("Open-Meteo response is missing hourly data")
    times = hourly.get("time")
    if not isinstance(times, list) or not times:
        raise SystemExit("Open-Meteo response contains no hourly timestamps")

    source_columns: dict[str, list[float]] = {}
    for variable in SOURCE_VARIABLES:
        values = hourly.get(variable)
        if not isinstance(values, list) or len(values) != len(times):
            raise SystemExit(f"Open-Meteo variable {variable} is missing or misaligned")
        if any(value is None for value in values):
            raise SystemExit(f"Open-Meteo source variable {variable} contains missing values")
        try:
            numeric = [float(value) for value in values]
        except (TypeError, ValueError) as exc:
            raise SystemExit(f"Open-Meteo source variable {variable} is non-numeric") from exc
        if not all(math.isfinite(value) for value in numeric):
            raise SystemExit(f"Open-Meteo source variable {variable} contains non-finite values")
        source_columns[variable] = numeric

    apparent_temperature = [
        _apparent_temperature_celsius(temperature, humidity, wind_speed)
        for temperature, humidity, wind_speed in zip(
            source_columns["temperature_2m"],
            source_columns["relative_humidity_2m"],
            source_columns["wind_speed_10m"],
            strict=True,
        )
    ]
    columns: dict[str, list[float]] = {
        "temperature_2m": source_columns["temperature_2m"],
        "relative_humidity_2m": source_columns["relative_humidity_2m"],
        "apparent_temperature": apparent_temperature,
        "precipitation": source_columns["precipitation"],
        "wind_speed_10m": source_columns["wind_speed_10m"],
    }

    csv_output = args.csv_output.resolve()
    csv_output.parent.mkdir(parents=True, exist_ok=True)
    with csv_output.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.writer(destination)
        writer.writerow(("timestamp", *OUTPUT_VARIABLES))
        for index, timestamp in enumerate(times):
            writer.writerow((timestamp, *(columns[name][index] for name in OUTPUT_VARIABLES)))

    metadata = {
        "schema": "energyforecast-point5-weather/v1",
        "research_mode": "W1_idealized_reanalysis",
        "operational_forecast_claim": False,
        "provider": "Open-Meteo Historical Weather API",
        "reanalysis_model": "ERA5-Land",
        "api_endpoint": API_BASE,
        "request_parameters": params,
        "requested_location": {
            "name": "Sceaux, Hauts-de-Seine, France",
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "coordinate_semantics": "approximate city centre; exact UCI household coordinates are unpublished",
            "geocoding_source": GEOCODING_SOURCE,
            "geocoding_source_url": GEOCODING_SOURCE_URL,
        },
        "returned_grid": {
            "latitude": payload.get("latitude"),
            "longitude": payload.get("longitude"),
            "elevation": payload.get("elevation"),
            "timezone": payload.get("timezone"),
            "utc_offset_seconds": payload.get("utc_offset_seconds"),
        },
        "source_hourly_variables": list(SOURCE_VARIABLES),
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
                "reason": "ERA5-Land/Open-Meteo apparent_temperature contained missing values; derive consistently for all rows rather than interpolate or mix definitions",
            }
        },
        "weather_missing_value_policy": "fail_on_missing_source_variable; no interpolation",
        "hourly_rows": len(times),
        "first_timestamp": times[0],
        "last_timestamp": times[-1],
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
