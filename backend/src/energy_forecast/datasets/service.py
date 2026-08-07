"""Dataset catalog operations and bounded upload staging."""

from __future__ import annotations

import csv
import re
import unicodedata
from collections.abc import Mapping
from typing import Any, BinaryIO, cast
from uuid import UUID

from energy_forecast.artifacts.models import ArtifactPurpose
from energy_forecast.artifacts.service import ArtifactService
from energy_forecast.datasets.models import (
    DatasetChanges,
    DatasetImportRecord,
    DatasetNotFoundError,
    DatasetPage,
    DatasetRecord,
    DatasetUploadError,
    ImportProfile,
    StagedDatasetImport,
    UploadTooLargeError,
)
from energy_forecast.datasets.ports import DatasetCatalogRepository

_ALLOWED_SUFFIXES = frozenset({".csv", ".txt"})
_SNIFF_BYTES = 64 * 1024
_SUSPICIOUS_PREFIXES = (
    b"%PDF-",
    b"PK\x03\x04",
    b"\x7fELF",
    b"MZ",
    b"\x89PNG",
    b"\xff\xd8\xff",
)
_IMPORT_OPTION_KEYS = frozenset(
    {
        "delimiter",
        "decimal_separator",
        "timestamp_column",
        "timestamp_format",
        "timestamp_semantics",
        "timezone",
        "energy_column",
        "power_column",
        "unit",
        "duplicate_policy",
    }
)


class _LimitedReader:
    def __init__(self, stream: BinaryIO, limit: int) -> None:
        self._stream = stream
        self._limit = limit
        self._count = 0

    def read(self, size: int = -1) -> bytes:
        remaining_with_probe = self._limit - self._count + 1
        requested = remaining_with_probe if size < 0 else min(size, remaining_with_probe)
        chunk = self._stream.read(requested)
        if not isinstance(chunk, bytes):
            raise TypeError("Dataset streams must return bytes")
        self._count += len(chunk)
        if self._count > self._limit:
            raise UploadTooLargeError(self._limit)
        return chunk


class DatasetService:
    """Coordinate short database transactions with immutable artifact storage."""

    def __init__(
        self,
        repository: DatasetCatalogRepository,
        artifacts: ArtifactService,
        *,
        max_upload_bytes: int,
    ) -> None:
        self._repository = repository
        self._artifacts = artifacts
        self._max_upload_bytes = max_upload_bytes

    async def create(self, *, name: str, description: str | None) -> DatasetRecord:
        return await self._repository.create(name=name, description=description)

    async def list(self, *, page: int, page_size: int) -> DatasetPage:
        return await self._repository.list(page=page, page_size=page_size)

    async def get(self, dataset_id: UUID) -> DatasetRecord:
        dataset = await self._repository.get(dataset_id)
        if dataset is None:
            raise DatasetNotFoundError("Dataset was not found")
        return dataset

    async def update(self, dataset_id: UUID, changes: DatasetChanges) -> DatasetRecord:
        dataset = await self._repository.update(dataset_id, changes)
        if dataset is None:
            raise DatasetNotFoundError("Dataset was not found")
        return dataset

    async def delete(self, dataset_id: UUID) -> None:
        deleted = await self._repository.delete_if_empty(dataset_id)
        if not deleted:
            raise DatasetNotFoundError("Dataset was not found")

    async def stage_import(
        self,
        *,
        dataset_id: UUID,
        stream: BinaryIO,
        original_name: str | None,
        import_profile: ImportProfile,
        import_options: Mapping[str, Any],
    ) -> StagedDatasetImport:
        await self.get(dataset_id)
        safe_options = _sanitize_import_options(import_options)
        safe_name, suffix = _sanitize_filename(original_name)
        detected_format = _inspect_csv_like(stream, import_profile, safe_options)
        stream.seek(0)
        artifact = await self._artifacts.create(
            cast(BinaryIO, _LimitedReader(stream, self._max_upload_bytes)),
            purpose=ArtifactPurpose.RAW_DATASET,
            media_type="text/csv",
            suffix=suffix,
            original_name=safe_name,
        )
        try:
            import_record = await self._repository.stage_import(
                dataset_id=dataset_id,
                artifact=artifact,
                import_profile=import_profile,
                import_options=safe_options,
                detected_format=detected_format,
            )
        except BaseException:
            await self._artifacts.delete(artifact.id)
            raise
        return StagedDatasetImport(
            import_record=import_record,
            artifact_id=artifact.id,
            artifact_sha256=artifact.sha256,
        )

    async def get_import(self, import_id: UUID) -> DatasetImportRecord:
        import_record = await self._repository.get_import(import_id)
        if import_record is None:
            raise DatasetNotFoundError("Dataset import was not found")
        return import_record


def _sanitize_filename(original_name: str | None) -> tuple[str, str]:
    if original_name is None:
        raise DatasetUploadError("dataset_filename_missing", "Ім'я завантаженого файлу відсутнє.")
    normalized = unicodedata.normalize("NFKC", original_name)
    basename = re.split(r"[/\\]", normalized)[-1]
    basename = "".join(character for character in basename if ord(character) >= 32)
    basename = basename.strip(" .")
    suffix = "." + basename.rsplit(".", 1)[-1].lower() if "." in basename else ""
    if suffix not in _ALLOWED_SUFFIXES:
        raise DatasetUploadError(
            "dataset_file_type_unsupported",
            "Дозволено завантажувати лише CSV або TXT файли.",
        )
    if len(basename) > 255:
        stem_limit = 255 - len(suffix)
        basename = basename[:stem_limit].rstrip(" .") + suffix
    if not basename or basename == suffix:
        basename = f"upload{suffix}"
    return basename, suffix


def _sanitize_import_options(import_options: Mapping[str, Any]) -> dict[str, Any]:
    unknown = set(import_options) - _IMPORT_OPTION_KEYS
    if unknown:
        raise DatasetUploadError(
            "dataset_import_options_invalid",
            "Параметри імпорту містять непідтримувані поля.",
        )
    sanitized: dict[str, Any] = {}
    for key, value in import_options.items():
        if not isinstance(value, str):
            raise DatasetUploadError(
                "dataset_import_options_invalid",
                "Параметри імпорту повинні бути текстовими значеннями.",
            )
        normalized = value.strip() if key != "delimiter" else value
        disallowed_control = any(
            ord(character) < 32 and not (key == "delimiter" and character == "\t")
            for character in normalized
        )
        if not normalized or len(normalized) > 160 or disallowed_control:
            raise DatasetUploadError(
                "dataset_import_options_invalid",
                "Параметри імпорту містять небезпечне або завелике значення.",
            )
        sanitized[key] = normalized
    return sanitized


def _inspect_csv_like(
    stream: BinaryIO,
    import_profile: ImportProfile,
    import_options: Mapping[str, Any],
) -> dict[str, Any]:
    sample = stream.read(_SNIFF_BYTES)
    if not isinstance(sample, bytes):
        raise TypeError("Dataset streams must return bytes")
    if not sample:
        raise DatasetUploadError("dataset_upload_empty", "Завантажений файл порожній.")
    if b"\x00" in sample or any(sample.startswith(prefix) for prefix in _SUSPICIOUS_PREFIXES):
        raise _unexpected_content()
    try:
        text = sample.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise _unexpected_content() from error
    if text.lstrip().lower().startswith(("<!doctype html", "<html", "<?xml", "{", "[")):
        raise _unexpected_content()

    lines = [line for line in text.splitlines() if line.strip()][:12]
    if len(lines) < 2:
        raise _unexpected_content()
    delimiter = _resolve_delimiter(text, import_profile, import_options)
    try:
        rows = list(csv.reader(lines, delimiter=delimiter, strict=True))
    except csv.Error as error:
        raise _unexpected_content() from error
    widths = [len(row) for row in rows]
    if min(widths) < 2 or len(set(widths)) != 1:
        raise _unexpected_content()
    return {"encoding": "utf-8", "delimiter": delimiter, "column_count": widths[0]}


def _resolve_delimiter(
    text: str,
    import_profile: ImportProfile,
    import_options: Mapping[str, Any],
) -> str:
    if import_profile is ImportProfile.UCI:
        return ";"
    configured = import_options.get("delimiter")
    if isinstance(configured, str) and configured:
        return configured
    try:
        return csv.Sniffer().sniff(text, delimiters=",;\t|").delimiter
    except csv.Error as error:
        raise _unexpected_content() from error


def _unexpected_content() -> DatasetUploadError:
    return DatasetUploadError(
        "dataset_content_unsupported",
        "Вміст файлу не схожий на підтримувані табличні CSV-дані.",
    )
