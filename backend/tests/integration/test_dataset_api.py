from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select

from energy_forecast.api import create_app
from energy_forecast.config import Settings
from energy_forecast.database.models import Artifact, DatasetImport, DatasetVersion, Job
from energy_forecast.database.session import create_database_engine, create_session_factory
from tests.integration.conftest import upgrade_database


class PassingReadinessCheck:
    async def check(self) -> None:
        return None


def _settings(database_url: str, artifact_root: Path, *, limit: int = 314_572_800) -> Settings:
    return Settings(
        database_url=SecretStr(database_url),
        artifact_root=artifact_root,
        max_upload_bytes=limit,
    )


async def _import_state(database_url: str, import_id: UUID) -> dict[str, Any]:
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            import_row = await session.get(DatasetImport, import_id)
            assert import_row is not None
            version = await session.get(DatasetVersion, import_row.dataset_version_id)
            job = await session.get(Job, import_row.job_id)
            assert version is not None
            assert job is not None
            artifact = await session.get(Artifact, version.raw_artifact_id)
            assert artifact is not None
            return {
                "import": import_row,
                "version": version,
                "job": job,
                "artifact": artifact,
            }
    finally:
        await engine.dispose()


async def _artifact_count(database_url: str) -> int:
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            return int(await session.scalar(select(func.count(Artifact.id))) or 0)
    finally:
        await engine.dispose()


@pytest.mark.integration
def test_dataset_crud_follows_pagination_patch_and_delete_contract(
    temporary_database_url: str,
    tmp_path: Path,
) -> None:
    upgrade_database(temporary_database_url)
    application = create_app(
        _settings(temporary_database_url, tmp_path / "artifacts"),
        PassingReadinessCheck(),
    )

    with TestClient(application, raise_server_exceptions=False) as client:
        first = client.post("/datasets", json={"name": "  Main meter  ", "description": "Raw"})
        second = client.post("/datasets", json={"name": "Second meter"})
        assert first.status_code == 201
        assert second.status_code == 201
        first_id = first.json()["id"]
        second_id = second.json()["id"]
        assert first.json()["name"] == "Main meter"

        page = client.get("/datasets", params={"page": 1, "page_size": 1})
        assert page.status_code == 200
        assert page.json()["total"] == 2
        assert len(page.json()["items"]) == 1

        patched = client.patch(f"/datasets/{first_id}", json={"description": None})
        assert patched.status_code == 200
        assert patched.json()["description"] is None
        assert client.patch(f"/datasets/{first_id}", json={}).status_code == 422

        deleted = client.delete(f"/datasets/{second_id}")
        assert deleted.status_code == 204
        assert deleted.content == b""
        missing = client.get(f"/datasets/{second_id}")
        assert missing.status_code == 404
        assert missing.headers["content-type"].startswith("application/problem+json")


@pytest.mark.integration
def test_upload_stages_immutable_artifact_version_import_and_job(
    temporary_database_url: str,
    tmp_path: Path,
) -> None:
    upgrade_database(temporary_database_url)
    artifact_root = tmp_path / "artifacts"
    application = create_app(
        _settings(temporary_database_url, artifact_root),
        PassingReadinessCheck(),
    )
    content = b"Date;Time;Global_active_power\n16/12/2006;17:24:00;4.216\n"

    with TestClient(application, raise_server_exceptions=False) as client:
        created = client.post("/datasets", json={"name": "UCI control"})
        dataset_id = created.json()["id"]
        accepted = client.post(
            f"/datasets/{dataset_id}/imports",
            data={"import_profile": "uci"},
            files={"file": (r"..\..\meter.CSV", content, "application/x-msdownload")},
        )
        assert accepted.status_code == 202
        assert set(accepted.json()) == {"import_id", "job_id", "status"}
        assert accepted.json()["status"] == "queued"
        assert "storage" not in accepted.text.lower()
        import_id = UUID(accepted.json()["import_id"])

        import_response = client.get(f"/dataset-imports/{import_id}")
        assert import_response.status_code == 200
        assert import_response.json()["dataset_id"] == dataset_id
        assert import_response.json()["job_id"] == accepted.json()["job_id"]
        assert import_response.json()["detected_format"]["delimiter"] == ";"

        conflict = client.delete(f"/datasets/{dataset_id}")
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "dataset_in_use"

        duplicate = client.post(
            f"/datasets/{dataset_id}/imports",
            data={"import_profile": "uci"},
            files={"file": ("same.txt", content, "text/plain")},
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["code"] == "dataset_source_conflict"

    state = asyncio.run(_import_state(temporary_database_url, import_id))
    artifact = state["artifact"]
    version = state["version"]
    job = state["job"]
    import_row = state["import"]
    assert artifact.original_name == "meter.CSV"
    assert artifact.storage_key != artifact.original_name
    assert artifact.sha256 == hashlib.sha256(content).hexdigest()
    assert artifact.size_bytes == len(content)
    assert (artifact_root / artifact.storage_key).read_bytes() == content
    assert version.status == "uploaded"
    assert version.source_sha256 == artifact.sha256
    assert import_row.status == "queued"
    assert job.job_type == "dataset_import"
    assert job.status == "queued"
    assert job.payload["artifact_id"] == str(artifact.id)
    assert asyncio.run(_artifact_count(temporary_database_url)) == 1
    assert len(list(artifact_root.iterdir())) == 1


@pytest.mark.integration
@pytest.mark.parametrize(
    ("filename", "content", "expected_status", "expected_code"),
    [
        ("empty.csv", b"", 422, "dataset_upload_empty"),
        ("image.png", b"timestamp,value\n2026-01-01,1\n", 422, "dataset_file_type_unsupported"),
        ("binary.csv", b"timestamp,value\nA,\x00B\n", 422, "dataset_content_unsupported"),
        (
            "large.csv",
            b"timestamp,value\n2026-01-01," + b"1" * 100 + b"\n",
            413,
            "dataset_upload_too_large",
        ),
    ],
)
def test_upload_rejections_leave_no_artifact_metadata_or_bytes(
    temporary_database_url: str,
    tmp_path: Path,
    filename: str,
    content: bytes,
    expected_status: int,
    expected_code: str,
) -> None:
    upgrade_database(temporary_database_url)
    artifact_root = tmp_path / "artifacts"
    application = create_app(
        _settings(temporary_database_url, artifact_root, limit=64),
        PassingReadinessCheck(),
    )

    with TestClient(application, raise_server_exceptions=False) as client:
        dataset_id = client.post("/datasets", json={"name": "Security test"}).json()["id"]
        response = client.post(
            f"/datasets/{dataset_id}/imports",
            data={"import_profile": "generic_csv", "delimiter": ","},
            files={"file": (filename, content, "text/csv")},
        )

    assert response.status_code == expected_status
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == expected_code
    assert asyncio.run(_artifact_count(temporary_database_url)) == 0
    assert list(artifact_root.iterdir()) == []


def test_runtime_openapi_documents_dataset_and_multipart_contract(tmp_path: Path) -> None:
    schema = create_app(
        Settings(artifact_root=tmp_path),
        PassingReadinessCheck(),
    ).openapi()

    assert schema["paths"]["/datasets"]["post"]["operationId"] == "createDataset"
    upload = schema["paths"]["/datasets/{datasetId}/imports"]["post"]
    assert upload["operationId"] == "createDatasetImport"
    assert "multipart/form-data" in upload["requestBody"]["content"]
    assert "202" in upload["responses"]
    assert "413" in upload["responses"]
    assert "DatasetImportAccepted" in schema["components"]["schemas"]
