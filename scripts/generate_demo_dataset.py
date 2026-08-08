from __future__ import annotations

import argparse
import csv
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path


def build_energy_kwh(timestamp: datetime, hour_index: int) -> float:
    """Return deterministic, non-negative hourly demand with daily/weekly structure."""
    hour = timestamp.hour
    weekday = timestamp.weekday()

    daily_cycle = 0.28 * math.sin(2.0 * math.pi * (hour - 7) / 24.0)
    morning_peak = 0.34 * math.exp(-((hour - 8) / 2.4) ** 2)
    evening_peak = 0.62 * math.exp(-((hour - 19) / 3.0) ** 2)
    weekend_adjustment = -0.12 if weekday >= 5 else 0.0
    slow_cycle = 0.08 * math.sin(2.0 * math.pi * hour_index / (24.0 * 30.0))
    value = 1.18 + daily_cycle + morning_peak + evening_peak + weekend_adjustment + slow_cycle
    return round(max(0.2, value), 4)


def generate(output: Path, days: int) -> int:
    if days < 60:
        raise ValueError("days must be at least 60 so the demo remains useful for lagged ML workflows")

    output.parent.mkdir(parents=True, exist_ok=True)
    start = datetime(2025, 1, 1, tzinfo=UTC)
    hours = days * 24

    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "energy_kwh"])
        for hour_index in range(hours):
            timestamp = start + timedelta(hours=hour_index)
            writer.writerow([timestamp.isoformat(), f"{build_energy_kwh(timestamp, hour_index):.4f}"])

    return hours


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a deterministic synthetic hourly EnergyForecast demo CSV."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("build/demo-energy.csv"),
        help="Output CSV path (default: build/demo-energy.csv).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=120,
        help="Number of hourly days to generate; minimum 60 (default: 120).",
    )
    args = parser.parse_args()

    rows = generate(args.output, args.days)
    print(f"Generated {rows} hourly rows at {args.output}")


if __name__ == "__main__":
    main()
