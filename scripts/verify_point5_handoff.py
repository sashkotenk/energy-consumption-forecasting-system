#!/usr/bin/env python3
"""Validate the public Point-5 handoff contract without accessing private planning material."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_EXPERIMENTS = {
    "E00",
    "E01",
    "E10",
    "E11",
    "E12",
    "E20",
    "E21",
    "E22",
    "E30",
    "E31",
    "E32",
}
EXPECTED_SCHEMA_HASHES = {
    "base_v1": "e58c9eb93e8ce16823bb4c5010346818b78850ff6825c48d287dc6a884151e9d",
    "base_quality_v1": "f335e7668a525686b6111e34386db569f0e76d755c0a1202f48727a68a7be80b",
}
EXPECTED_SPLIT = "uci_2009_quarters_2010_test_v1"
EXPECTED_FINAL_TEST_START = "2010-01-01T00:00:00+00:00"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--path",
        type=Path,
        default=ROOT / "docs" / "evidence" / "point5-handoff.json",
    )
    parser.add_argument("--require-dataset-binding", action="store_true")
    args = parser.parse_args()

    path = args.path.resolve()
    _require(path.is_file(), f"Missing Point-5 handoff: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    _require(payload.get("schema") == "energyforecast-point5-handoff/v1", "Unsupported handoff schema")
    _require(
        isinstance(payload.get("release_candidate_sha"), str)
        and re.fullmatch(r"[0-9a-f]{40}", payload["release_candidate_sha"]) is not None,
        "Point-5 handoff must identify a 40-character release candidate SHA",
    )

    dataset = payload.get("dataset")
    _require(isinstance(dataset, dict), "Point-5 handoff requires dataset binding metadata")
    status = dataset.get("binding_status")
    _require(
        status in {"pending_external_uci_profile", "bound_external_uci_profile"},
        "Unexpected dataset binding status",
    )
    source_sha = dataset.get("source_sha256")
    version_id = dataset.get("prepared_dataset_version_id")
    if status == "bound_external_uci_profile":
        _require(
            isinstance(source_sha, str) and re.fullmatch(r"[0-9a-f]{64}", source_sha) is not None,
            "Bound UCI handoff requires a valid source SHA-256",
        )
        try:
            UUID(str(version_id))
        except (ValueError, TypeError) as error:
            raise SystemExit("Bound UCI handoff requires a valid prepared dataset UUID") from error
    else:
        _require(source_sha is None and version_id is None, "Pending dataset binding must not invent values")
        _require(not args.require_dataset_binding, "Dataset binding is required for this verification")

    dependencies = payload.get("dependency_baseline")
    _require(isinstance(dependencies, dict), "Dependency baseline is missing")
    _require(bool(dependencies.get("backend_direct")), "Backend locked direct versions are missing")
    _require(bool(dependencies.get("frontend_direct")), "Frontend locked direct versions are missing")
    lockfiles = dependencies.get("lockfiles")
    _require(isinstance(lockfiles, dict) and len(lockfiles) == 2, "Lockfile SHA-256 baseline is incomplete")
    for relative, digest in lockfiles.items():
        lock_path = ROOT / relative
        _require(lock_path.is_file(), f"Missing lockfile referenced by handoff: {relative}")
        _require(
            isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
            f"Invalid lockfile SHA-256 for {relative}",
        )
        _require(_sha256(lock_path) == digest, f"Lockfile SHA-256 drifted for {relative}")

    schemas = payload.get("feature_schemas")
    _require(isinstance(schemas, dict), "Feature schemas are missing")
    observed = {
        str(value.get("version")): str(value.get("sha256"))
        for value in schemas.values()
        if isinstance(value, dict)
    }
    _require(observed == EXPECTED_SCHEMA_HASHES, "Feature schema versions/hashes drifted")

    split = payload.get("split_definition")
    _require(isinstance(split, dict), "Split definition is missing")
    _require(split.get("version") == EXPECTED_SPLIT, "Split definition version drifted")
    _require(split.get("purge_hours") == 24, "Split purge must remain 24 hours")
    _require(split.get("final_test_start") == EXPECTED_FINAL_TEST_START, "Final-test start drifted")
    folds = split.get("validation_folds")
    _require(isinstance(folds, list) and len(folds) == 4, "Exactly four validation folds are required")

    matrix = payload.get("experiment_matrix")
    _require(isinstance(matrix, list), "Experiment matrix is missing")
    identifiers = {item.get("id") for item in matrix if isinstance(item, dict)}
    _require(identifiers == EXPECTED_EXPERIMENTS, "Experiment matrix E00-E32 is incomplete or drifted")
    weather_entries = {item["id"]: item for item in matrix if item.get("id") in {"E20", "E21", "E22"}}
    _require(
        all(item.get("status") == "blocked_until_real_weather_source" for item in weather_entries.values()),
        "W1 experiment entries must remain blocked until a real weather source exists",
    )

    isolation = payload.get("final_test_isolation")
    _require(isinstance(isolation, dict), "Final-test isolation declaration is missing")
    _require(isolation.get("confirmed") is True, "Final-test isolation must be explicitly confirmed")
    _require(isolation.get("selection_uses_final_test") is False, "Selection must not use final-test data")
    _require(
        isolation.get("selection_must_be_persisted_before_final_test_indexes") is True,
        "Recommendation must be persisted before final-test indexes are requested",
    )

    for field in ("reproduction_scripts", "result_templates"):
        values = payload.get(field)
        _require(isinstance(values, list) and values, f"{field} is missing")
        for relative in values:
            _require(isinstance(relative, str) and (ROOT / relative).is_file(), f"Missing {field} path: {relative}")

    benchmark = payload.get("benchmark_machine_profile")
    _require(isinstance(benchmark, dict), "Benchmark machine profile reference is missing")
    _require(isinstance(benchmark.get("profile"), dict), "Benchmark machine profile is not populated")

    print(f"Verified Point-5 handoff contract: {path}")


if __name__ == "__main__":
    main()
