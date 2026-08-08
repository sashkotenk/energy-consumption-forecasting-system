#!/usr/bin/env python3
"""Record deterministic size metadata for a completed Vite production build."""

from __future__ import annotations

import argparse
import gzip
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _entry(path: Path, root: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": len(payload),
        "gzip_bytes": len(gzip.compress(payload, compresslevel=9, mtime=0)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, default=Path("frontend/dist"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    dist = args.dist.resolve()
    if not dist.is_dir():
        raise SystemExit(f"Vite build directory does not exist: {dist}")

    assets = sorted(
        (path for path in dist.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(dist).as_posix(),
    )
    if not assets:
        raise SystemExit("Vite build directory contains no files")

    entries = [_entry(path, dist) for path in assets]
    js = [entry for entry in entries if str(entry["path"]).endswith(".js")]
    css = [entry for entry in entries if str(entry["path"]).endswith(".css")]
    largest_js = max(js, key=lambda entry: int(entry["bytes"]), default=None)

    payload = {
        "schema": "energyforecast-frontend-bundle-evidence/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "release_commit": os.environ.get("GITHUB_SHA") or os.environ.get("CODE_COMMIT") or "unknown",
        "build": "npm run build (Vite production build)",
        "measurements": {
            "asset_count": len(entries),
            "total_bytes": sum(int(entry["bytes"]) for entry in entries),
            "total_gzip_bytes": sum(int(entry["gzip_bytes"]) for entry in entries),
            "javascript_bytes": sum(int(entry["bytes"]) for entry in js),
            "javascript_gzip_bytes": sum(int(entry["gzip_bytes"]) for entry in js),
            "css_bytes": sum(int(entry["bytes"]) for entry in css),
            "css_gzip_bytes": sum(int(entry["gzip_bytes"]) for entry in css),
            "largest_javascript_asset": largest_js,
        },
        "assets": entries,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
