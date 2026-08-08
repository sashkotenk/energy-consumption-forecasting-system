#!/usr/bin/env python3
"""Verify SHA-256 checksums in the public release evidence manifest."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "evidence" / "handoff-manifest.json"
PRIVATE_PATTERN = re.compile(
    r"(^|/)(AGENTS\.md|prompts/|checklists?/|Пункт плану|План виконання|EnergyForecast-private)"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    if not MANIFEST.is_file():
        raise SystemExit(f"Missing evidence manifest: {MANIFEST.relative_to(ROOT)}")

    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if payload.get("schema") != "energyforecast-handoff-manifest/v1":
        raise SystemExit("Unsupported evidence manifest schema")
    if not payload.get("release_candidate_sha"):
        raise SystemExit("Evidence manifest must identify a release candidate SHA")

    entries = payload.get("files")
    if not isinstance(entries, list) or not entries:
        raise SystemExit("Evidence manifest must contain at least one file checksum")

    errors: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("Manifest file entry is not an object")
            continue
        raw_path = entry.get("path")
        expected = entry.get("sha256")
        if not isinstance(raw_path, str) or not isinstance(expected, str):
            errors.append("Manifest file entry requires string path and sha256")
            continue
        if raw_path in seen:
            errors.append(f"Duplicate evidence path: {raw_path}")
            continue
        seen.add(raw_path)
        if PRIVATE_PATTERN.search(raw_path):
            errors.append(f"Private path is forbidden in evidence manifest: {raw_path}")
            continue
        path = (ROOT / raw_path).resolve()
        try:
            path.relative_to((ROOT / "docs" / "evidence").resolve())
        except ValueError:
            errors.append(f"Evidence path escapes docs/evidence: {raw_path}")
            continue
        if path == MANIFEST.resolve():
            errors.append("Manifest must not checksum itself")
            continue
        if not path.is_file():
            errors.append(f"Missing evidence file: {raw_path}")
            continue
        actual = _sha256(path)
        if actual != expected.lower():
            errors.append(f"Checksum mismatch for {raw_path}: expected {expected}, got {actual}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Verified {len(entries)} evidence SHA-256 checksums")


if __name__ == "__main__":
    main()
