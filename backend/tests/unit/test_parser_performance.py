from __future__ import annotations

import tracemalloc
from io import BytesIO

import pytest

from energy_forecast.datasets.parsers import UciDatasetParser


@pytest.mark.performance
def test_chunked_uci_parser_has_bounded_incremental_memory() -> None:
    header = (
        b"Date;Time;Global_active_power;Global_reactive_power;Voltage;Global_intensity;"
        b"Sub_metering_1;Sub_metering_2;Sub_metering_3\n"
    )
    row = b"16/12/2006;17:24:00;4.216;0.418;234.840;18.400;0;1;17\n"
    source = BytesIO(header + row * 50_000)

    tracemalloc.start()
    parsed = sum(
        len(batch.measurements)
        for batch in UciDatasetParser().parse_batches(source, batch_size=1_000)
    )
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert parsed == 50_000
    assert peak_bytes < 12 * 1024 * 1024
