"""Streaming parsers for the control UCI source and explicitly mapped CSV files."""

from __future__ import annotations

import csv
import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from io import TextIOWrapper
from typing import Any, BinaryIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from energy_forecast.datasets.models import DatasetUploadError, ImportProfile

UCI_COLUMNS = (
    "Date",
    "Time",
    "Global_active_power",
    "Global_reactive_power",
    "Voltage",
    "Global_intensity",
    "Sub_metering_1",
    "Sub_metering_2",
    "Sub_metering_3",
)
_SUPPORTED_DELIMITERS = (",", ";", "\t")
_MISSING_TOKENS = frozenset({"", "?", "nan", "NaN", "NAN"})


class ParseStatus(StrEnum):
    VALID = "valid"
    WARNING = "warning"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class ParsedMeasurement:
    source_row_number: int
    observed_at: datetime
    timestamp_original: str
    timezone_context: str | None
    interval_seconds: int | None
    energy_kwh: float | None = None
    active_power_kw: float | None = None
    reactive_power_kw: float | None = None
    voltage_v: float | None = None
    current_a: float | None = None
    sub_metering_1_wh: float | None = None
    sub_metering_2_wh: float | None = None
    sub_metering_3_wh: float | None = None
    parse_status: ParseStatus = ParseStatus.VALID
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ParseIssue:
    source_row_number: int
    code: str
    message: str
    column_name: str | None = None
    raw_value: str | None = None


@dataclass(frozen=True, slots=True)
class ParseBatch:
    measurements: tuple[ParsedMeasurement, ...]
    issues: tuple[ParseIssue, ...]
    rows_read: int


class StreamingDatasetParser:
    """Parser interface whose yielded batches cap retained row state."""

    def parse_batches(self, stream: BinaryIO, *, batch_size: int) -> Iterator[ParseBatch]:
        raise NotImplementedError


class UciDatasetParser(StreamingDatasetParser):
    """Parse the official nine-column UCI household-power text format."""

    def __init__(self, *, timezone: str = "Europe/Paris") -> None:
        self._timezone_name = timezone
        self._timezone = _load_timezone(timezone)

    def parse_batches(self, stream: BinaryIO, *, batch_size: int) -> Iterator[ParseBatch]:
        _validate_batch_size(batch_size)
        text = TextIOWrapper(stream, encoding="utf-8-sig", newline="")
        reader = csv.reader(text, delimiter=";", strict=True)
        try:
            header = tuple(next(reader))
        except StopIteration as error:
            raise DatasetUploadError("dataset_empty", "Файл даних не містить заголовка.") from error
        if header != UCI_COLUMNS:
            raise DatasetUploadError(
                "uci_columns_invalid",
                "UCI-файл повинен містити дев'ять офіційних колонок у визначеному порядку.",
            )

        measurements: list[ParsedMeasurement] = []
        issues: list[ParseIssue] = []
        rows_read = 0
        for source_row_number, row in enumerate(reader, start=2):
            rows_read += 1
            measurement, row_issues = self._parse_row(source_row_number, row)
            if measurement is not None:
                measurements.append(measurement)
            issues.extend(row_issues)
            if len(measurements) + len(issues) >= batch_size:
                yield ParseBatch(tuple(measurements), tuple(issues), rows_read)
                measurements.clear()
                issues.clear()
        if measurements or issues:
            yield ParseBatch(tuple(measurements), tuple(issues), rows_read)

    def _parse_row(
        self, source_row_number: int, row: list[str]
    ) -> tuple[ParsedMeasurement | None, tuple[ParseIssue, ...]]:
        if len(row) != len(UCI_COLUMNS):
            return None, (
                ParseIssue(
                    source_row_number,
                    "column_count",
                    f"Expected {len(UCI_COLUMNS)} columns, received {len(row)}.",
                ),
            )
        timestamp_original = f"{row[0]} {row[1]}"
        try:
            observed_at = datetime.strptime(timestamp_original, "%d/%m/%Y %H:%M:%S").replace(
                tzinfo=self._timezone
            )
        except ValueError:
            return None, (
                ParseIssue(
                    source_row_number,
                    "timestamp_invalid",
                    "Date and time do not match dd/mm/yyyy HH:MM:SS.",
                    "Date/Time",
                    timestamp_original[:160],
                ),
            )

        values: list[float | None] = []
        row_issues: list[ParseIssue] = []
        flags: list[str] = []
        for column_name, raw_value in zip(UCI_COLUMNS[2:], row[2:], strict=True):
            value, issue = _parse_number(raw_value, decimal_separator=".")
            values.append(value)
            if issue == "missing":
                flags.append(f"missing:{column_name}")
            elif issue is not None:
                flags.append(f"parse_error:{column_name}")
                row_issues.append(
                    ParseIssue(
                        source_row_number,
                        "number_invalid",
                        "Numeric value could not be parsed.",
                        column_name,
                        raw_value[:160],
                    )
                )
        status = (
            ParseStatus.INVALID
            if row_issues
            else ParseStatus.WARNING
            if flags
            else ParseStatus.VALID
        )
        return (
            ParsedMeasurement(
                source_row_number=source_row_number,
                observed_at=observed_at,
                timestamp_original=timestamp_original,
                timezone_context=self._timezone_name,
                interval_seconds=60,
                active_power_kw=values[0],
                reactive_power_kw=values[1],
                voltage_v=values[2],
                current_a=values[3],
                sub_metering_1_wh=values[4],
                sub_metering_2_wh=values[5],
                sub_metering_3_wh=values[6],
                parse_status=status,
                quality_flags=tuple(flags),
            ),
            tuple(row_issues),
        )


@dataclass(frozen=True, slots=True)
class GenericCsvMapping:
    timestamp_column: str
    target_semantic: str
    target_column: str
    unit: str
    timezone: str | None
    timestamp_format: str | None
    timestamp_semantics: str
    interval_seconds: int | None
    delimiter: str
    decimal_separator: str
    optional_columns: Mapping[str, str]

    @classmethod
    def from_options(
        cls, options: Mapping[str, Any], *, detected_delimiter: str | None = None
    ) -> GenericCsvMapping:
        timestamp_column = _required_option(options, "timestamp_column")
        energy_column = _optional_option(options, "energy_column")
        power_column = _optional_option(options, "power_column")
        selected = _optional_option(options, "target_semantic")
        if selected is None:
            if bool(energy_column) == bool(power_column):
                raise DatasetUploadError(
                    "target_mapping_invalid",
                    "Потрібно вибрати рівно одну основну семантику: energy або active_power.",
                )
            selected = "energy" if energy_column else "active_power"
        if selected not in {"energy", "active_power"}:
            raise DatasetUploadError(
                "target_mapping_invalid", "Невідома семантика цільової колонки."
            )
        target_column = energy_column if selected == "energy" else power_column
        if target_column is None:
            raise DatasetUploadError(
                "target_mapping_invalid", "Для вибраної семантики не задано цільову колонку."
            )
        unit = _required_option(options, "unit").lower()
        compatible_units = {"energy": {"kwh", "wh"}, "active_power": {"kw", "w"}}
        if unit not in compatible_units[selected]:
            raise DatasetUploadError(
                "target_unit_invalid", "Одиниця вимірювання не відповідає семантиці цілі."
            )
        delimiter = _optional_option(options, "delimiter") or detected_delimiter
        if delimiter not in _SUPPORTED_DELIMITERS:
            raise DatasetUploadError("delimiter_invalid", "Роздільник CSV не підтримується.")
        decimal_separator = _optional_option(options, "decimal_separator") or "."
        if decimal_separator not in {".", ","}:
            raise DatasetUploadError(
                "decimal_separator_invalid", "Десятковий роздільник не підтримується."
            )
        timezone = _optional_option(options, "timezone")
        if timezone is not None:
            _load_timezone(timezone)
        timestamp_semantics = _optional_option(options, "timestamp_semantics") or "interval_start"
        if timestamp_semantics not in {"interval_start", "interval_end"}:
            raise DatasetUploadError("timestamp_semantics_invalid", "Невідома семантика часу.")
        interval_raw = _optional_option(options, "interval_seconds")
        interval_seconds = int(interval_raw) if interval_raw is not None else None
        if interval_seconds is not None and interval_seconds <= 0:
            raise DatasetUploadError("interval_invalid", "Інтервал повинен бути додатним.")
        optional_columns = {
            field: value
            for field in (
                "reactive_power_kw",
                "voltage_v",
                "current_a",
                "sub_metering_1_wh",
                "sub_metering_2_wh",
                "sub_metering_3_wh",
            )
            if (value := _optional_option(options, f"{field}_column")) is not None
        }
        return cls(
            timestamp_column=timestamp_column,
            target_semantic=selected,
            target_column=target_column,
            unit=unit,
            timezone=timezone,
            timestamp_format=_optional_option(options, "timestamp_format"),
            timestamp_semantics=timestamp_semantics,
            interval_seconds=interval_seconds,
            delimiter=delimiter,
            decimal_separator=decimal_separator,
            optional_columns=optional_columns,
        )


class GenericCsvParser(StreamingDatasetParser):
    def __init__(self, mapping: GenericCsvMapping) -> None:
        self._mapping = mapping

    def parse_batches(self, stream: BinaryIO, *, batch_size: int) -> Iterator[ParseBatch]:
        _validate_batch_size(batch_size)
        text = TextIOWrapper(stream, encoding="utf-8-sig", newline="")
        reader = csv.DictReader(text, delimiter=self._mapping.delimiter, strict=True)
        header = tuple(reader.fieldnames or ())
        required = {self._mapping.timestamp_column, self._mapping.target_column}
        missing = sorted(required - set(header))
        if missing:
            raise DatasetUploadError(
                "mapped_columns_missing",
                f"У CSV відсутні зіставлені колонки: {', '.join(missing)}.",
            )

        measurements: list[ParsedMeasurement] = []
        issues: list[ParseIssue] = []
        rows_read = 0
        for source_row_number, row in enumerate(reader, start=2):
            rows_read += 1
            measurement, row_issues = self._parse_row(source_row_number, row)
            if measurement is not None:
                measurements.append(measurement)
            issues.extend(row_issues)
            if len(measurements) + len(issues) >= batch_size:
                yield ParseBatch(tuple(measurements), tuple(issues), rows_read)
                measurements.clear()
                issues.clear()
        if measurements or issues:
            yield ParseBatch(tuple(measurements), tuple(issues), rows_read)

    def _parse_row(
        self, source_row_number: int, row: Mapping[str, str | None]
    ) -> tuple[ParsedMeasurement | None, tuple[ParseIssue, ...]]:
        timestamp_raw = row.get(self._mapping.timestamp_column) or ""
        try:
            observed_at = _parse_timestamp(
                timestamp_raw,
                timestamp_format=self._mapping.timestamp_format,
                timezone=self._mapping.timezone,
            )
        except ValueError:
            return None, (
                ParseIssue(
                    source_row_number,
                    "timestamp_invalid",
                    "Timestamp could not be parsed or lacks timezone context.",
                    self._mapping.timestamp_column,
                    timestamp_raw[:160],
                ),
            )
        if self._mapping.timestamp_semantics == "interval_end":
            if self._mapping.interval_seconds is None:
                return None, (
                    ParseIssue(
                        source_row_number,
                        "interval_required",
                        "interval_seconds is required for interval-end timestamps.",
                    ),
                )
            observed_at -= timedelta(seconds=self._mapping.interval_seconds)

        raw_target = row.get(self._mapping.target_column) or ""
        target, issue = _parse_number(raw_target, self._mapping.decimal_separator)
        flags: list[str] = []
        issues: list[ParseIssue] = []
        if issue == "missing":
            flags.append(f"missing:{self._mapping.target_column}")
        elif issue is not None:
            flags.append(f"parse_error:{self._mapping.target_column}")
            issues.append(
                ParseIssue(
                    source_row_number,
                    "number_invalid",
                    "Target value could not be parsed.",
                    self._mapping.target_column,
                    raw_target[:160],
                )
            )
        energy_kwh: float | None = None
        active_power_kw: float | None = None
        if target is not None:
            if self._mapping.target_semantic == "energy":
                energy_kwh = target / 1000 if self._mapping.unit == "wh" else target
            else:
                active_power_kw = target / 1000 if self._mapping.unit == "w" else target

        optional_values: dict[str, float | None] = {}
        for field, column in self._mapping.optional_columns.items():
            value, optional_issue = _parse_number(
                row.get(column) or "", self._mapping.decimal_separator
            )
            optional_values[field] = value
            if optional_issue == "missing":
                flags.append(f"missing:{column}")
            elif optional_issue is not None:
                flags.append(f"parse_error:{column}")
                issues.append(
                    ParseIssue(
                        source_row_number,
                        "number_invalid",
                        "Optional numeric value could not be parsed.",
                        column,
                        (row.get(column) or "")[:160],
                    )
                )
        status = (
            ParseStatus.INVALID if issues else ParseStatus.WARNING if flags else ParseStatus.VALID
        )
        return (
            ParsedMeasurement(
                source_row_number=source_row_number,
                observed_at=observed_at,
                timestamp_original=timestamp_raw[:80],
                timezone_context=self._mapping.timezone,
                interval_seconds=self._mapping.interval_seconds,
                energy_kwh=energy_kwh,
                active_power_kw=active_power_kw,
                reactive_power_kw=optional_values.get("reactive_power_kw"),
                voltage_v=optional_values.get("voltage_v"),
                current_a=optional_values.get("current_a"),
                sub_metering_1_wh=optional_values.get("sub_metering_1_wh"),
                sub_metering_2_wh=optional_values.get("sub_metering_2_wh"),
                sub_metering_3_wh=optional_values.get("sub_metering_3_wh"),
                parse_status=status,
                quality_flags=tuple(flags),
            ),
            tuple(issues),
        )


def create_parser(
    profile: ImportProfile,
    options: Mapping[str, Any],
    *,
    detected_delimiter: str | None = None,
) -> StreamingDatasetParser:
    if profile is ImportProfile.UCI:
        return UciDatasetParser(timezone=_optional_option(options, "timezone") or "Europe/Paris")
    mapping = GenericCsvMapping.from_options(options, detected_delimiter=detected_delimiter)
    return GenericCsvParser(mapping)


def preview_csv(
    stream: BinaryIO,
    *,
    profile: ImportProfile,
    configured_delimiter: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Return a bounded, non-persistent structural preview with delimiter/decimal hints."""
    if not 1 <= limit <= 20:
        raise ValueError("Preview limit must be between 1 and 20")
    sample = stream.read(64 * 1024)
    try:
        text = sample.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise DatasetUploadError("encoding_invalid", "CSV повинен мати кодування UTF-8.") from error
    delimiter = (
        ";" if profile is ImportProfile.UCI else configured_delimiter or _sniff_delimiter(text)
    )
    rows = list(csv.reader(text.splitlines(), delimiter=delimiter, strict=True))
    if not rows:
        raise DatasetUploadError("dataset_empty", "Файл даних порожній.")
    header = rows[0]
    preview_rows = rows[1 : limit + 1]
    return {
        "encoding": "utf-8",
        "delimiter": delimiter,
        "decimal_separator": _detect_decimal_separator(preview_rows),
        "columns": header,
        "rows": preview_rows,
        "truncated": len(rows) > limit + 1 or len(sample) == 64 * 1024,
    }


def _parse_number(raw_value: str, decimal_separator: str) -> tuple[float | None, str | None]:
    value = raw_value.strip()
    if value in _MISSING_TOKENS:
        return None, "missing"
    normalized = value.replace(decimal_separator, ".") if decimal_separator == "," else value
    try:
        number = float(normalized)
    except ValueError:
        return None, "invalid"
    if not math.isfinite(number):
        return None, "non_finite"
    return number, None


def _parse_timestamp(value: str, *, timestamp_format: str | None, timezone: str | None) -> datetime:
    parsed = (
        datetime.strptime(value, timestamp_format)
        if timestamp_format
        else datetime.fromisoformat(value.replace("Z", "+00:00"))
    )
    if parsed.tzinfo is None:
        if timezone is None:
            raise ValueError("Naive timestamp requires timezone context")
        parsed = parsed.replace(tzinfo=_load_timezone(timezone))
    return parsed.astimezone(UTC)


def _load_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as error:
        raise DatasetUploadError("timezone_invalid", "Невідомий часовий пояс.") from error


def _sniff_delimiter(text: str) -> str:
    try:
        return csv.Sniffer().sniff(text, delimiters=";,	").delimiter
    except csv.Error as error:
        raise DatasetUploadError(
            "delimiter_unknown", "Не вдалося визначити роздільник CSV."
        ) from error


def _detect_decimal_separator(rows: list[list[str]]) -> str:
    dot = sum(cell.count(".") for row in rows for cell in row)
    comma = sum(cell.count(",") for row in rows for cell in row)
    return "," if comma > dot else "."


def _required_option(options: Mapping[str, Any], key: str) -> str:
    value = _optional_option(options, key)
    if value is None:
        raise DatasetUploadError("mapping_required", f"Параметр {key} є обов'язковим.")
    return value


def _optional_option(options: Mapping[str, Any], key: str) -> str | None:
    value = options.get(key)
    return value if isinstance(value, str) and value else None


def _validate_batch_size(batch_size: int) -> None:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
