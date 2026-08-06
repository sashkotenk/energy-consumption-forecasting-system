from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest

from energy_forecast.artifacts import LocalArtifactStore, UnsafeArtifactPathError


class FailingStream(BytesIO):
    def __init__(self) -> None:
        super().__init__(b"first chunk")
        self._reads = 0

    def read(self, size: int | None = -1) -> bytes:
        self._reads += 1
        if self._reads > 1:
            raise OSError("simulated interrupted upload")
        return super().read(5)


def test_stream_write_is_atomic_and_returns_checksum(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path)
    content = b"hour,energy_kwh\n0,1.25\n"

    stored = store.put(BytesIO(content), suffix=".CSV")

    assert stored.storage_key.endswith(".csv")
    assert stored.size_bytes == len(content)
    assert stored.sha256 == sha256(content).hexdigest()
    assert all(not path.name.startswith(".write-") for path in tmp_path.iterdir())
    with store.open(stored.storage_key) as artifact_stream:
        assert artifact_stream.read() == content


def test_same_content_has_distinct_keys_and_the_same_checksum(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path)
    content = b"same content"

    first = store.put(BytesIO(content), suffix=".bin")
    second = store.put(BytesIO(content), suffix=".bin")

    assert first.storage_key != second.storage_key
    assert first.sha256 == second.sha256
    assert len(list(tmp_path.iterdir())) == 2


@pytest.mark.parametrize(
    "unsafe_key",
    ["../outside", "nested/file.bin", "/tmp/file.bin", r"C:\outside\file.bin"],
)
def test_open_and_delete_reject_unsafe_keys(tmp_path: Path, unsafe_key: str) -> None:
    store = LocalArtifactStore(tmp_path)

    with pytest.raises(UnsafeArtifactPathError):
        store.open(unsafe_key)
    with pytest.raises(UnsafeArtifactPathError):
        store.delete(unsafe_key)


@pytest.mark.parametrize(
    "unsafe_suffix",
    ["../csv", ".tar.gz", "/tmp", r"C:\temp", ".bad/name"],
)
def test_put_rejects_unsafe_suffixes(tmp_path: Path, unsafe_suffix: str) -> None:
    store = LocalArtifactStore(tmp_path)

    with pytest.raises(UnsafeArtifactPathError):
        store.put(BytesIO(b"content"), suffix=unsafe_suffix)

    assert list(tmp_path.iterdir()) == []


def test_failed_stream_leaves_no_partial_artifact(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path)

    with pytest.raises(OSError, match="interrupted upload"):
        store.put(FailingStream(), suffix=".csv")

    assert list(tmp_path.iterdir()) == []


def test_delete_is_controlled_and_idempotent(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path)
    stored = store.put(BytesIO(b"temporary"))

    assert store.delete(stored.storage_key) is True
    assert store.delete(stored.storage_key) is False
    with pytest.raises(FileNotFoundError):
        store.open(stored.storage_key)
