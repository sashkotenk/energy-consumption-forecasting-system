#!/usr/bin/env python3
"""Generate the public Point-5 experimental handoff from executable repository contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from energy_forecast.ml.features import FeatureSchema
from energy_forecast.ml.splits import (
    FINAL_TEST_START,
    FORECAST_HORIZON,
    SPLIT_DEFINITION_V1,
    VALIDATION_PERIODS,
)

ROOT = Path(__file__).resolve().parents[1]
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DEPENDENCY_NAME_RE = re.compile(r"^([A-Za-z0-9_.-]+)")

EXPERIMENT_MATRIX: tuple[dict[str, Any], ...] = (
    {
        "id": "E00",
        "weather_mode": "consumption_only",
        "features": "daily seasonality",
        "algorithm": "seasonal_naive_24",
        "purpose": "baseline",
        "status": "operational",
    },
    {
        "id": "E01",
        "weather_mode": "consumption_only",
        "features": "weekly seasonality",
        "algorithm": "seasonal_naive_168",
        "purpose": "diagnostic",
        "status": "operational",
    },
    {
        "id": "E10",
        "weather_mode": "W0",
        "features": "lag+rolling+calendar",
        "algorithm": "ridge",
        "purpose": "linear control",
        "status": "operational",
    },
    {
        "id": "E11",
        "weather_mode": "W0",
        "features": "lag+rolling+calendar",
        "algorithm": "random_forest",
        "purpose": "nonlinear ensemble",
        "status": "operational",
    },
    {
        "id": "E12",
        "weather_mode": "W0",
        "features": "lag+rolling+calendar",
        "algorithm": "hist_gradient_boosting",
        "purpose": "boosting",
        "status": "operational",
    },
    {
        "id": "E20",
        "weather_mode": "W1",
        "features": "base+weather",
        "algorithm": "ridge",
        "purpose": "weather ablation",
        "status": "blocked_until_real_weather_source",
    },
    {
        "id": "E21",
        "weather_mode": "W1",
        "features": "base+weather",
        "algorithm": "random_forest",
        "purpose": "weather ablation",
        "status": "blocked_until_real_weather_source",
    },
    {
        "id": "E22",
        "weather_mode": "W1",
        "features": "base+weather",
        "algorithm": "hist_gradient_boosting",
        "purpose": "weather ablation",
        "status": "blocked_until_real_weather_source",
    },
    {
        "id": "E30",
        "weather_mode": "W0",
        "features": "base",
        "algorithm": "selected_final_configurations",
        "quality_profile": "complete_only",
        "purpose": "imputation sensitivity",
        "status": "operational_protocol",
    },
    {
        "id": "E31",
        "weather_mode": "W0",
        "features": "base",
        "algorithm": "selected_final_configurations",
        "quality_profile": "coverage_gte_80pct",
        "purpose": "threshold sensitivity",
        "status": "operational_protocol",
    },
    {
        "id": "E32",
        "weather_mode": "W0",
        "features": "base",
        "algorithm": "selected_final_configurations",
        "quality_profile": "coverage_gte_90pct",
        "purpose": "main mode",
        "status": "operational_protocol",
    },
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_head() -> str:
    env_sha = os.environ.get("GITHUB_SHA") or os.environ.get("CODE_COMMIT")
    if env_sha and re.fullmatch(r"[0-9a-f]{40}", env_sha):
        return env_sha
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _dependency_name(requirement: str) -> str:
    match = DEPENDENCY_NAME_RE.match(requirement)
    if match is None:
        raise ValueError(f"Unable to extract dependency name from {requirement!r}")
    return match.group(1).lower().replace("_", "-")


def _backend_dependency_versions() -> dict[str, str]:
    pyproject = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((ROOT / "backend" / "uv.lock").read_text(encoding="utf-8"))
    requirements = list(pyproject["project"]["dependencies"])
    requirements.extend(pyproject.get("dependency-groups", {}).get("dev", []))
    direct_names = {_dependency_name(value) for value in requirements}
    versions = {
        str(package["name"]).lower().replace("_", "-"): str(package["version"])
        for package in lock["package"]
        if "version" in package
    }
    missing = sorted(direct_names.difference(versions))
    if missing:
        raise ValueError(f"Direct backend dependencies missing from uv.lock: {missing}")
    return {name: versions[name] for name in sorted(direct_names)}


def _frontend_dependency_versions() -> dict[str, str]:
    lock = json.loads((ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    root_package = lock["packages"][""]
    names = set(root_package.get("dependencies", {}))
    names.update(root_package.get("devDependencies", {}))
    result: dict[str, str] = {}
    for name in sorted(names):
        package = lock["packages"].get(f"node_modules/{name}")
        if not isinstance(package, dict) or "version" not in package:
            raise ValueError(f"Direct frontend dependency missing from package-lock.json: {name}")
        result[name] = str(package["version"])
    return result


def _first_from(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("FROM "):
            return stripped.split()[1]
    raise ValueError(f"No FROM instruction found in {path.relative_to(ROOT)}")


def _timescale_image() -> str:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    match = re.search(r"image:\s*(timescale/timescaledb:[^\s]+)", compose)
    if match is None:
        raise ValueError("Pinned TimescaleDB image was not found in docker-compose.yml")
    return match.group(1)


def _feature_schema(*, include_quality_features: bool) -> dict[str, Any]:
    schema = FeatureSchema.create(include_quality_features=include_quality_features)
    return {
        "version": schema.version,
        "sha256": schema.sha256,
        "forecast_horizon_hours": schema.forecast_horizon,
        "feature_count": len(schema.names),
        "names": list(schema.names),
        "dtypes": list(schema.dtypes),
    }


def _split_definition() -> dict[str, Any]:
    purge_hours = int(FORECAST_HORIZON.total_seconds() // 3600)
    return {
        "version": SPLIT_DEFINITION_V1,
        "forecast_horizon_hours": purge_hours,
        "purge_hours": purge_hours,
        "validation_folds": [
            {
                "fold": index,
                "validation_start": start.isoformat(),
                "validation_end_exclusive": end.isoformat(),
                "train_rule": "origin + 24h < validation_start",
            }
            for index, (start, end) in enumerate(VALIDATION_PERIODS, start=1)
        ],
        "final_test_start": FINAL_TEST_START.isoformat(),
        "final_test_rule": "origin >= final_test_start",
        "final_test_access": "after recommendation is persisted",
    }


def _benchmark_reference(path: Path | None) -> dict[str, Any]:
    selected = path
    if selected is None:
        historical = ROOT / "docs" / "evidence" / "release-benchmark.json"
        selected = historical if historical.is_file() else None
    if selected is None:
        return {"source": None, "schema": None, "release_commit": None, "profile": None}
    resolved = selected.resolve()
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    try:
        display = resolved.relative_to(ROOT).as_posix()
    except ValueError:
        display = str(resolved)
    return {
        "source": display,
        "schema": payload.get("schema"),
        "release_commit": payload.get("release_commit"),
        "profile": payload.get("profile"),
    }


def _dataset_binding(sha256: str | None, version: str | None) -> dict[str, Any]:
    if bool(sha256) != bool(version):
        raise ValueError("dataset SHA-256 and prepared dataset version must be supplied together")
    if sha256 is not None:
        normalized = sha256.lower()
        if SHA256_RE.fullmatch(normalized) is None:
            raise ValueError("dataset SHA-256 must be exactly 64 hexadecimal characters")
        UUID(version)
        return {
            "profile": "uci_individual_household_electric_power_consumption",
            "source_filename": "household_power_consumption.txt",
            "source_sha256": normalized,
            "prepared_dataset_version_id": version,
            "binding_status": "bound_external_uci_profile",
            "uci_source_in_repository": False,
        }
    return {
        "profile": "uci_individual_household_electric_power_consumption",
        "source_filename": "household_power_consumption.txt",
        "source_sha256": None,
        "prepared_dataset_version_id": None,
        "binding_status": "pending_external_uci_profile",
        "uci_source_in_repository": False,
        "binding_rule": (
            "Bind both values from the immutable external UCI import/hourly version immediately "
            "before the final full-dataset experiment; never invent either value."
        ),
    }


def _dependency_baseline() -> dict[str, Any]:
    uv_lock = ROOT / "backend" / "uv.lock"
    npm_lock = ROOT / "frontend" / "package-lock.json"
    return {
        "python": (ROOT / "backend" / ".python-version").read_text(encoding="utf-8").strip(),
        "node": (ROOT / ".nvmrc").read_text(encoding="utf-8").strip(),
        "uv": "0.12.2",
        "database_image": _timescale_image(),
        "backend_base_image": _first_from(ROOT / "backend" / "Dockerfile"),
        "web_base_image": _first_from(ROOT / "frontend" / "Dockerfile"),
        "edge_base_image": _first_from(ROOT / "infrastructure" / "nginx" / "Dockerfile"),
        "lockfiles": {
            "backend/uv.lock": _sha256(uv_lock),
            "frontend/package-lock.json": _sha256(npm_lock),
        },
        "backend_direct": _backend_dependency_versions(),
        "frontend_direct": _frontend_dependency_versions(),
    }


def _build_handoff(args: argparse.Namespace) -> dict[str, Any]:
    release_sha = args.release_candidate_sha or _git_head()
    if re.fullmatch(r"[0-9a-f]{40}", release_sha) is None:
        raise ValueError("release candidate SHA must be a 40-character lowercase Git SHA")
    dataset = _dataset_binding(args.dataset_sha256, args.prepared_dataset_version)
    if args.require_dataset_binding and dataset["binding_status"] != "bound_external_uci_profile":
        raise ValueError("full UCI handoff requires --dataset-sha256 and --prepared-dataset-version")

    return {
        "schema": "energyforecast-point5-handoff/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "release_candidate_sha": release_sha,
        "dataset": dataset,
        "dependency_baseline": _dependency_baseline(),
        "feature_schemas": {
            "operational_w0": _feature_schema(include_quality_features=False),
            "quality_sensitivity": _feature_schema(include_quality_features=True),
        },
        "split_definition": _split_definition(),
        "experiment_matrix": list(EXPERIMENT_MATRIX),
        "selection_protocol": {
            "primary": "lowest mean_cv_mae",
            "practical_tie_pct": 1.0,
            "stability": "lowest std_cv_mae",
            "stability_tie_pct": 5.0,
            "next": "lower prediction time",
            "simplicity_order": ["ridge", "hist_gradient_boosting", "random_forest"],
            "final_test_evaluations_per_selected_configuration": 1,
        },
        "benchmark_machine_profile": _benchmark_reference(args.benchmark_json),
        "reproduction_scripts": [
            "scripts/run_uci_profile.ps1",
            "scripts/generate_point5_handoff.py",
            "scripts/generate_release_benchmark.py",
            "scripts/generate_system_benchmark.py",
            "scripts/benchmark_compose_startup.sh",
            "scripts/measure_frontend_bundle.py",
            "scripts/verify.ps1",
        ],
        "result_templates": [
            "docs/evidence/point5/final-results-template.csv",
            "docs/evidence/point5/horizon-results-template.csv",
        ],
        "final_test_isolation": {
            "confirmed": True,
            "selection_uses_final_test": False,
            "final_test_start": FINAL_TEST_START.isoformat(),
            "selection_must_be_persisted_before_final_test_indexes": True,
            "architecture_decision": (
                "docs/architecture/adr/ADR-022-experiment-selection-before-final-test.md"
            ),
            "regression_guard": "backend/tests/unit/test_ml_guard.py",
        },
        "weather_boundary": {
            "operational_mode": "W0",
            "w1_status": "unsupported_until_real_weather_source",
            "claim_policy": "no weather-benefit result before a real weather-source experiment",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-sha256")
    parser.add_argument("--prepared-dataset-version")
    parser.add_argument("--release-candidate-sha")
    parser.add_argument("--benchmark-json", type=Path)
    parser.add_argument("--require-dataset-binding", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = _build_handoff(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
