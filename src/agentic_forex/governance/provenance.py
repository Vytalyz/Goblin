from __future__ import annotations

import hashlib
import platform
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from agentic_forex.config import Settings
from agentic_forex.governance.models import DatasetSnapshot, EnvironmentSnapshot, ExperimentDataProvenance, FeatureBuildVersion
from agentic_forex.utils.io import read_json, write_json
from agentic_forex.workflows.contracts import StrategySpec


def build_data_provenance(spec: StrategySpec, settings: Settings, *, stage: str) -> ExperimentDataProvenance:
    dataset_snapshot = build_dataset_snapshot(spec, settings)
    feature_build = build_feature_build_version(settings)
    payload = {
        "candidate_id": spec.candidate_id,
        "stage": stage,
        "dataset_snapshot_id": dataset_snapshot.snapshot_id,
        "feature_version_id": feature_build.feature_version_id,
        "label_version_id": feature_build.label_version_id,
        "calendar_version_id": _version_for_path(settings.economic_calendar_path),
        "execution_cost_model_version": _hash_json(spec.execution_cost_model.model_dump(mode="json")),
        "risk_envelope_version": _hash_json(spec.risk_envelope.model_dump(mode="json")),
        "strategy_spec_version": _hash_json(spec.model_dump(mode="json")),
    }
    provenance_id = _hash_json(payload)
    report_path = settings.paths().reports_dir / spec.candidate_id / "data_provenance.json"
    provenance = ExperimentDataProvenance(
        provenance_id=provenance_id,
        candidate_id=spec.candidate_id,
        stage=stage,
        dataset_snapshot=dataset_snapshot,
        feature_build=feature_build,
        calendar_version_id=payload["calendar_version_id"],
        execution_cost_model_version=payload["execution_cost_model_version"],
        risk_envelope_version=payload["risk_envelope_version"],
        strategy_spec_version=payload["strategy_spec_version"],
        report_path=report_path,
    )
    write_json(report_path, provenance.model_dump(mode="json"))
    return provenance


def build_environment_snapshot(
    settings: Settings,
    *,
    candidate_id: str,
    mt5_build: str | None = None,
    metaeditor_version: str | None = None,
) -> EnvironmentSnapshot:
    dependency_snapshot_hash = _dependency_snapshot_hash(settings)
    payload = {
        "python_version": sys.version,
        "dependency_snapshot_hash": dependency_snapshot_hash,
        "os_platform": platform.platform(),
        "machine_id": socket.gethostname(),
        "git_revision": _git_revision(settings.project_root),
        "mt5_build": mt5_build,
        "metaeditor_version": metaeditor_version,
    }
    environment_id = _hash_json(payload)
    report_path = settings.paths().reports_dir / candidate_id / "environment_snapshot.json"
    snapshot = EnvironmentSnapshot(
        environment_id=environment_id,
        python_version=sys.version,
        dependency_snapshot_hash=dependency_snapshot_hash,
        os_platform=platform.platform(),
        machine_id=socket.gethostname(),
        git_revision=payload["git_revision"],
        mt5_build=mt5_build,
        metaeditor_version=metaeditor_version,
        report_path=report_path,
    )
    write_json(report_path, snapshot.model_dump(mode="json"))
    return snapshot


def build_dataset_snapshot(spec: StrategySpec, settings: Settings) -> DatasetSnapshot:
    parquet_path = settings.paths().normalized_research_dir / f"{spec.instrument.lower()}_{spec.execution_granularity.lower()}.parquet"
    qa_path = settings.paths().market_quality_reports_dir / f"{spec.instrument.lower()}_{spec.execution_granularity.lower()}.json"
    extraction_utc = _path_mtime_utc(parquet_path)
    dataset_start_utc = None
    dataset_end_utc = None
    if parquet_path.exists():
        frame = pd.read_parquet(parquet_path, columns=["timestamp_utc"])
        if not frame.empty:
            timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True)
            dataset_start_utc = timestamps.min().isoformat().replace("+00:00", "Z")
            dataset_end_utc = timestamps.max().isoformat().replace("+00:00", "Z")
    snapshot_payload = {
        "source": settings.data.canonical_source,
        "instrument": spec.instrument,
        "parquet_version": _version_for_path(parquet_path),
        "qa_version": _version_for_path(qa_path),
        "session_filters": spec.session_policy.allowed_hours_utc,
        "dataset_start_utc": dataset_start_utc,
        "dataset_end_utc": dataset_end_utc,
    }
    snapshot_id = _hash_json(snapshot_payload)
    return DatasetSnapshot(
        snapshot_id=snapshot_id,
        source=settings.data.canonical_source,
        extraction_utc=extraction_utc,
        instrument=spec.instrument,
        symbol_mapping={spec.instrument: spec.instrument},
        dataset_start_utc=dataset_start_utc,
        dataset_end_utc=dataset_end_utc,
        session_filters=spec.session_policy.allowed_hours_utc,
        qa_report_path=qa_path if qa_path.exists() else None,
        parquet_path=parquet_path,
    )


def build_feature_build_version(settings: Settings) -> FeatureBuildVersion:
    feature_paths = [settings.project_root / "src" / "agentic_forex" / "features" / "service.py"]
    label_paths = [settings.project_root / "src" / "agentic_forex" / "labels" / "service.py"]
    return FeatureBuildVersion(
        feature_version_id=_hash_paths(feature_paths),
        label_version_id=_hash_paths(label_paths),
        feature_paths=feature_paths,
        label_paths=label_paths,
    )


def load_data_provenance(candidate_id: str, settings: Settings) -> ExperimentDataProvenance | None:
    path = settings.paths().reports_dir / candidate_id / "data_provenance.json"
    if not path.exists():
        return None
    return ExperimentDataProvenance.model_validate(read_json(path))


def load_environment_snapshot(candidate_id: str, settings: Settings) -> EnvironmentSnapshot | None:
    path = settings.paths().reports_dir / candidate_id / "environment_snapshot.json"
    if not path.exists():
        return None
    return EnvironmentSnapshot.model_validate(read_json(path))


def _hash_paths(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path).encode("utf-8"))
        if path.exists():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def _dependency_snapshot_hash(settings: Settings) -> str:
    pyproject = settings.project_root / "pyproject.toml"
    version = _version_for_path(pyproject)
    if version:
        return version
    fallback_paths = [
        settings.project_root / "config" / "default.toml",
        settings.project_root / "src" / "agentic_forex" / "config" / "models.py",
    ]
    return _hash_paths(fallback_paths)


def _version_for_path(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    digest.update(str(path).encode("utf-8"))
    digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def _hash_json(payload: dict) -> str:
    encoded = repr(sorted(payload.items())).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _git_revision(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception:  # noqa: BLE001
        return None
    revision = result.stdout.strip()
    return revision or None


def _path_mtime_utc(path: Path) -> str:
    if not path.exists():
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat().replace("+00:00", "Z")
