#!/usr/bin/env python3
"""Fetch the Point-5 ERA5-Land weather ablation input from Open-Meteo.

This is research evidence, not an operational weather forecast.  The requested
coordinate is the GeoNames centre of Sceaux, France, because the UCI dataset does
not publish the household's exact coordinates.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

LATITUDE = 48.776442
LONGITUDE = 2.290258
GEOCODING_SOURCE = "GeoNames Sceaux populated-place centre"
GEOCODING_SOURCE_URL = "https://www.geonames.org/search.html?country=FR&q=Sceaux"
API_BASE = "https://archive-api.open-meteo.com/v1/archive"
VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "precipitation",
    "wind_speed_10m",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        "hourly": ",".join(VARIABLES),
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
    columns: dict[str, list[object]] = {}
    for variable in VARIABLES:
        values = hourly.get(variable)
        if not isinstance(values, list) or len(values) != len(times):
            raise SystemExit(f"Open-Meteo variable {variable} is missing or misaligned")
        if any(value is None for value in values):
            raise SystemExit(f"Open-Meteo variable {variable} contains missing values")
        columns[variable] = values

    csv_output = args.csv_output.resolve()
    csv_output.parent.mkdir(parents=True, exist_ok=True)
    with csv_output.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.writer(destination)
        writer.writerow(("timestamp", *VARIABLES))
        for index, timestamp in enumerate(times):
            writer.writerow((timestamp, *(columns[name][index] for name in VARIABLES)))

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
        "hourly_variables": list(VARIABLES),
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
