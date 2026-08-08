#!/usr/bin/env python3
"""Verify repository-local documentation links and Mermaid source structure."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
MERMAID_HEADERS = (
    "flowchart ",
    "graph ",
    "sequenceDiagram",
    "classDiagram",
    "erDiagram",
    "stateDiagram",
    "stateDiagram-v2",
)


def _markdown_files() -> list[Path]:
    files = [ROOT / "README.md", ROOT / "ARCHITECTURE.md"]
    files.extend(sorted((ROOT / "docs").rglob("*.md")))
    return [path for path in files if path.is_file()]


def _resolve_link(source: Path, raw_target: str) -> Path | None:
    target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
    if not target or target.startswith(("#", "http://", "https://", "mailto:")):
        return None
    target = unquote(target.split("#", 1)[0].split("?", 1)[0])
    if not target:
        return None
    return (source.parent / target).resolve()


def verify_links() -> list[str]:
    errors: list[str] = []
    for source in _markdown_files():
        text = source.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK.finditer(text):
            resolved = _resolve_link(source, match.group(1))
            if resolved is None:
                continue
            try:
                resolved.relative_to(ROOT)
            except ValueError:
                errors.append(f"{source.relative_to(ROOT)}: link escapes repository: {match.group(1)}")
                continue
            if not resolved.exists():
                errors.append(f"{source.relative_to(ROOT)}: missing link target: {match.group(1)}")
    return errors


def verify_mermaid() -> list[str]:
    errors: list[str] = []
    diagram_dir = ROOT / "docs" / "diagrams"
    diagrams = sorted(diagram_dir.glob("*.mmd"))
    if not diagrams:
        return ["docs/diagrams: no Mermaid sources found"]
    for path in diagrams:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            errors.append(f"{path.relative_to(ROOT)}: empty Mermaid source")
            continue
        first = lines[0]
        if not any(first.startswith(header) for header in MERMAID_HEADERS):
            errors.append(f"{path.relative_to(ROOT)}: unsupported Mermaid header: {first}")
        if "```" in path.read_text(encoding="utf-8"):
            errors.append(f"{path.relative_to(ROOT)}: .mmd sources must not contain Markdown fences")
    return errors


def main() -> None:
    errors = [*verify_links(), *verify_mermaid()]
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Documentation links verified across {len(_markdown_files())} Markdown files")
    print(f"Mermaid source structure verified across {len(list((ROOT / 'docs' / 'diagrams').glob('*.mmd')))} diagrams")


if __name__ == "__main__":
    main()
