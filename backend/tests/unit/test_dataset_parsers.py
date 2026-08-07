from __future__ import annotations

from io import BytesIO

import pytest

from energy_forecast.datasets.models import DatasetUploadError, ImportProfile
from energy_forecast.datasets.parsers import (
    GenericCsvMapping,
    GenericCsvParser,
    ParseStatus,
    UciDatasetParser,
    preview_csv,
)

UCI_HEADER = (
    b"Date;Time;Global_active_power;Global_reactive_power;Voltage;Global_intensity;"
    b"Sub_metering_1;Sub_metering_2;Sub_metering_3\n"
)


def test_uci_parser_accepts_official_columns_and_preserves_missing_as_null() -> None:
    source = BytesIO(
        UCI_HEADER
        + b"16/12/2006;17:24:00;4.216;0.418;234.840;18.400;0.000;1.000;17.000\n"
        + b"16/12/2006;17:25:00;?;0.436;233.630;18.400;0.000;;16.000\n"
    )

    batches = list(UciDatasetParser().parse_batches(source, batch_size=1))
    rows = [row for batch in batches for row in batch.measurements]

    assert len(rows) == 2
    assert rows[0].source_row_number == 2
    assert rows[0].active_power_kw == pytest.approx(4.216)
    assert rows[0].interval_seconds == 60
    assert rows[1].active_power_kw is None
    assert rows[1].sub_metering_2_wh is None
    assert rows[1].parse_status is ParseStatus.WARNING
    assert "missing:Global_active_power" in rows[1].quality_flags


def test_uci_parser_reports_malformed_rows_with_source_numbers() -> None:
    source = BytesIO(
        UCI_HEADER
        + b"not-a-date;17:24:00;4.2;0.4;230;18;0;1;17\n"
        + b"16/12/2006;17:25:00;bad;0.4;230;18;0;1;17\n"
    )

    batches = list(UciDatasetParser().parse_batches(source, batch_size=10))
    issues = [issue for batch in batches for issue in batch.issues]
    rows = [row for batch in batches for row in batch.measurements]

    assert [(issue.source_row_number, issue.code) for issue in issues] == [
        (2, "timestamp_invalid"),
        (3, "number_invalid"),
    ]
    assert len(rows) == 1
    assert rows[0].parse_status is ParseStatus.INVALID
    assert rows[0].active_power_kw is None


def test_generic_mapping_requires_timestamp_and_one_selected_target() -> None:
    with pytest.raises(DatasetUploadError, match="timestamp_column"):
        GenericCsvMapping.from_options(
            {"energy_column": "value", "unit": "kwh"}, detected_delimiter=","
        )

    with pytest.raises(DatasetUploadError, match="рівно одну"):
        GenericCsvMapping.from_options(
            {
                "timestamp_column": "time",
                "energy_column": "energy",
                "power_column": "power",
                "unit": "kwh",
            },
            detected_delimiter=",",
        )


def test_generic_parser_converts_decimal_comma_and_watts_with_timezone() -> None:
    mapping = GenericCsvMapping.from_options(
        {
            "timestamp_column": "when",
            "power_column": "load",
            "unit": "w",
            "timezone": "Europe/Kyiv",
            "decimal_separator": ",",
            "interval_seconds": "60",
        },
        detected_delimiter=";",
    )
    source = BytesIO(b"when;load\n2026-01-01 00:00:00;1250,5\n")

    batch = next(GenericCsvParser(mapping).parse_batches(source, batch_size=10))

    assert batch.measurements[0].active_power_kw == pytest.approx(1.2505)
    assert batch.measurements[0].observed_at.isoformat() == "2025-12-31T22:00:00+00:00"


def test_preview_is_bounded_and_detects_structure() -> None:
    preview = preview_csv(
        BytesIO(b"timestamp;energy\n2026-01-01T00:00:00Z;1,25\n2026-01-01T01:00:00Z;2,50\n"),
        profile=ImportProfile.GENERIC_CSV,
        limit=1,
    )

    assert preview["delimiter"] == ";"
    assert preview["decimal_separator"] == ","
    assert preview["columns"] == ["timestamp", "energy"]
    assert len(preview["rows"]) == 1
    assert preview["truncated"] is True
