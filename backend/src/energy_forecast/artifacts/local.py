"""Local-filesystem implementation of the ArtifactStore port."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO
from uuid import uuid4

from energy_forecast.artifacts.models import StoredArtifact, UnsafeArtifactPathError

_CHUNK_SIZE = 1024 * 1024
_KEY_PATTERN = re.compile(r"^[0-9a-f]{32}(?:\.[a-z0-9]{1,16})?$")
_SUFFIX_PATTERN = re.compile(r"^(?:\.[a-z0-9]{1,16})?$")


class LocalArtifactStore:
    """Publish artifacts atomically below one configured private root."""

    def __init__(self, root: Path) -> None:
        self._root = root.expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        if not self._root.is_dir():
            raise NotADirectoryError("Configured artifact root is not a directory")

    def put(self, stream: BinaryIO, *, suffix: str = "") -> StoredArtifact:
        """Stream bytes to a temporary file, then publish without overwriting."""
        normalized_suffix = self._validate_suffix(suffix)
        temporary_path = self._root / f".write-{uuid4().hex}.tmp"
        digest = hashlib.sha256()
        size_bytes = 0

        try:
            with temporary_path.open("xb") as target:
                while True:
                    chunk = stream.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    if not isinstance(chunk, bytes):
                        raise TypeError("Artifact streams must return bytes")
                    target.write(chunk)
                    digest.update(chunk)
                    size_bytes += len(chunk)
                target.flush()
                os.fsync(target.fileno())

            storage_key = self._publish_without_overwrite(temporary_path, normalized_suffix)
        finally:
            temporary_path.unlink(missing_ok=True)

        return StoredArtifact(
            storage_key=storage_key,
            size_bytes=size_bytes,
            sha256=digest.hexdigest(),
        )

    def open(self, storage_key: str) -> BinaryIO:
        """Open one regular artifact file for streaming reads."""
        path = self._path_for_key(storage_key)
        if path.is_symlink():
            raise UnsafeArtifactPathError("Storage key does not identify a regular file")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        file_descriptor = os.open(path, flags)
        try:
            if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
                raise UnsafeArtifactPathError("Storage key does not identify a regular file")
            return os.fdopen(file_descriptor, "rb")
        except BaseException:
            os.close(file_descriptor)
            raise

    def delete(self, storage_key: str) -> bool:
        """Delete one artifact; missing bytes are an idempotent no-op."""
        path = self._path_for_key(storage_key)
        if path.is_symlink():
            raise UnsafeArtifactPathError("Storage key does not identify a regular file")
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True

    def _publish_without_overwrite(self, temporary_path: Path, suffix: str) -> str:
        for _ in range(10):
            storage_key = f"{uuid4().hex}{suffix}"
            destination = self._path_for_key(storage_key)
            try:
                # A same-filesystem hard link makes the fully written file visible atomically.
                # Unlike os.replace(), it cannot overwrite an existing artifact on collision.
                os.link(temporary_path, destination)
            except FileExistsError:
                continue
            return storage_key
        raise FileExistsError("Could not allocate a collision-free artifact key")

    def _path_for_key(self, storage_key: str) -> Path:
        if not _KEY_PATTERN.fullmatch(storage_key):
            raise UnsafeArtifactPathError("Unsafe artifact storage key")
        if PurePosixPath(storage_key).is_absolute() or PureWindowsPath(storage_key).is_absolute():
            raise UnsafeArtifactPathError("Absolute artifact paths are forbidden")

        candidate = self._root / storage_key
        if candidate.parent != self._root:
            raise UnsafeArtifactPathError("Artifact path traversal is forbidden")
        return candidate

    @staticmethod
    def _validate_suffix(suffix: str) -> str:
        normalized = suffix.lower()
        if PurePosixPath(suffix).is_absolute() or PureWindowsPath(suffix).is_absolute():
            raise UnsafeArtifactPathError("Absolute artifact suffixes are forbidden")
        if not _SUFFIX_PATTERN.fullmatch(normalized):
            raise UnsafeArtifactPathError("Artifact suffix must be one safe extension")
        return normalized
