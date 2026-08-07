"""Export or verify the authoritative FastAPI OpenAPI document."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

# The export must not depend on a developer or CI database being configured.
os.environ.pop("DATABASE_URL", None)

from energy_forecast.api import create_app  # noqa: E402
from energy_forecast.config import Service, Settings  # noqa: E402

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPOSITORY_ROOT / "docs" / "api" / "openapi.json"


def build_openapi() -> dict[str, Any]:
    """Build the runtime contract without opening infrastructure connections."""
    app = create_app(settings=Settings(service=Service.API, database_url=None))
    schema = app.openapi()
    version = str(schema.get("openapi", ""))
    if not version.startswith("3.1"):
        raise RuntimeError(f"Expected OpenAPI 3.1, got {version or 'missing version'}")
    return schema


def serialize_openapi(schema: dict[str, Any]) -> str:
    """Serialize deterministically for reproducible SDK generation and drift checks."""
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def export_openapi(output: Path = DEFAULT_OUTPUT, *, check: bool = False) -> bool:
    """Write the contract, or return whether the committed contract is current."""
    rendered = serialize_openapi(build_openapi())
    if check:
        if not output.exists():
            return False
        return output.read_text(encoding="utf-8") == rendered

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8", newline="\n")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when openapi.json has drifted")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    current = export_openapi(args.output, check=args.check)
    if args.check and not current:
        print("OpenAPI drift detected. Run: cd backend && uv run python ../scripts/export_openapi.py")
        return 1
    if args.check:
        print("OpenAPI contract is synchronized.")
    else:
        print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
