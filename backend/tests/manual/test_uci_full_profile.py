from __future__ import annotations

import os
from pathlib import Path

import pytest

from energy_forecast.datasets.parsers import UciDatasetParser

pytestmark = pytest.mark.full_dataset


def test_external_uci_source_streams_without_repository_fixture() -> None:
    raw_path = os.environ.get("ENERGYFORECAST_UCI_PATH")
    if not raw_path:
        pytest.skip("ENERGYFORECAST_UCI_PATH must point to the external UCI household power file")

    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        pytest.fail(f"ENERGYFORECAST_UCI_PATH is not a file: {path}")

    row_count = 0
    issue_count = 0
    with path.open("rb") as source:
        for batch in UciDatasetParser().parse_batches(source, batch_size=10_000):
            row_count += len(batch.measurements)
            issue_count += len(batch.issues)

    assert row_count > 2_000_000
    assert issue_count >= 0
