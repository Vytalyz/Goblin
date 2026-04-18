from __future__ import annotations

import hashlib
import html
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from agentic_forex.config import Settings
from agentic_forex.governance.models import (
    FrozenArtifactSnapshot,
    LedgerPerformanceSummary,
    ProductionIncidentAttributionBucket,
    ProductionIncidentReport,
    ProductionIncidentStatus,
    TesterHarnessCheck,
    TradeDiffSummary,
)
from agentic_forex.utils.io import read_json, write_json

DEFAULT_BLOCKED_RELATED_CANDIDATES = {
    "AF-CAND-0263": ["AF-CAND-0263", "AF-CAND-0320", "AF-CAND-0332"],
}
DEFAULT_KNOWN_GOOD_WINDOWS = {
    "AF-CAND-0263": {
        "baseline_window_start": "2025-10-01",
        "baseline_window_end": "2026-03-20",
        "expected_min_trade_count": 100,
    }
}


def run_production_incident_analysis(
    settings: Settings,
    *,
    candidate_id: str,
    live_audit_csv: Path | None = None,
    mt5_replay_audit_csv: Path | None = None,
    deterministic_ledger_csv: Path | None = None,
    baseline_tester_report: Path | None = None,
    same_window_tester_report: Path | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    incident_id: str | None = None,
) -> ProductionIncidentReport:
    resolved_incident_id = incident_id or f"production-incident-{candidate_id}-{_utc_stamp()}"
    incident_dir = settings.paths().incidents_dir / candidate_id / resolved_incident_id
    incident_dir.mkdir(parents=True, exist_ok=True)

    live_audit_path = live_audit_csv or _discover_latest_live_audit(candidate_id)
    freeze = _freeze_artifacts(settings, candidate_id, live_audit_path=live_audit_path)
    harness_check = _build_harness_check(settings, candidate_id, baseline_tester_report)

    ledger_summaries = []
    for source_name, csv_path in (
        ("live_audit", live_audit_path),
        ("mt5_replay_audit", mt5_replay_audit_csv),
        ("deterministic_replay", deterministic_ledger_csv),
    ):
        if csv_path is not None:
            ledger_summaries.append(_summarize_ledger(source_name, csv_path))

    trade_diff_summaries: list[TradeDiffSummary] = []
    if live_audit_path is not None and mt5_replay_audit_csv is not None:
        trade_diff_summaries.append(
            compare_trade_ledgers(
                reference_csv=mt5_replay_audit_csv,
                observed_csv=live_audit_path,
                reference_name="mt5_replay_audit",
                observed_name="live_audit",
                output_csv=incident_dir / "mt5_replay_vs_live_trade_diff.csv",
                settings=settings,
            )
        )
    if live_audit_path is not None and deterministic_ledger_csv is not None:
        trade_diff_summaries.append(
            compare_trade_ledgers(
                reference_csv=deterministic_ledger_csv,
                observed_csv=live_audit_path,
                reference_name="deterministic_replay",
                observed_name="live_audit",
                output_csv=incident_dir / "deterministic_replay_vs_live_trade_diff.csv",
                settings=settings,
            )
        )

    artifact_paths = {
        "incident_dir": str(incident_dir),
    }
    if same_window_tester_report is not None:
        artifact_paths["same_window_tester_report_path"] = str(same_window_tester_report)
    if baseline_tester_report is not None:
        artifact_paths["baseline_tester_report_path"] = str(baseline_tester_report)

    attribution_bucket = _attribute_incident(
        harness_check=harness_check,
        ledger_summaries=ledger_summaries,
        trade_diff_summaries=trade_diff_summaries,
        has_mt5_replay=mt5_replay_audit_csv is not None,
    )
    workflow_status = _workflow_status(
        harness_check=harness_check,
        has_replay=mt5_replay_audit_csv is not None or deterministic_ledger_csv is not None,
        has_diff=bool(trade_diff_summaries),
        attribution_bucket=attribution_bucket,
    )
    notes = [
        f"{candidate_id} is treated as validation-suspended until the incident is attributed.",
        "MT5 replay evidence is authoritative only after the old known-good window reproduces nonzero trades.",
        "Deterministic replay remains research-only if it disagrees with MT5/live intrabar execution.",
        "AI may summarize and flag anomalies, but must not live-retune or promote candidates from this incident.",
    ]
    if window_start or window_end:
        notes.append(f"Incident window requested: {window_start or 'unspecified'} -> {window_end or 'unspecified'}.")

    report = ProductionIncidentReport(
        incident_id=resolved_incident_id,
        candidate_id=candidate_id,
        workflow_status=workflow_status,
        attribution_bucket=attribution_bucket,
        freeze=freeze,
        harness_check=harness_check,
        ledger_summaries=ledger_summaries,
        trade_diff_summaries=trade_diff_summaries,
        blocked_candidate_ids=DEFAULT_BLOCKED_RELATED_CANDIDATES.get(candidate_id, [candidate_id]),
        artifact_paths=artifact_paths,
        notes=notes,
        report_path=incident_dir / "incident_report.json",
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    write_json(
        settings.paths().incidents_dir / candidate_id / "latest_incident_report.json", report.model_dump(mode="json")
    )
    return report


def compare_trade_ledgers(
    *,
    reference_csv: Path,
    observed_csv: Path,
    reference_name: str,
    observed_name: str,
    output_csv: Path,
    settings: Settings,
) -> TradeDiffSummary:
    reference = _load_trade_ledger(reference_csv)
    observed = _load_trade_ledger(observed_csv)
    timestamp_tolerance = int(settings.validation.parity_timestamp_tolerance_seconds)
    exit_tolerance = int(settings.validation.parity_close_timing_tolerance_seconds)
    price_tolerance = float(settings.validation.parity_price_tolerance_pips)
    fill_tolerance = float(settings.validation.parity_fill_tolerance_pips)

    rows: list[dict[str, Any]] = []
    matched_observed: set[int] = set()
    classifications: dict[str, int] = {}
    matched_count = 0
    material_mismatch_count = 0

    for ref_index, ref_row in reference.iterrows():
        observed_index = _best_match(ref_row, observed, matched_observed, timestamp_tolerance)
        if observed_index is None:
            _increment(classifications, "missing_live_trade")
            rows.append(_diff_row(reference_name, observed_name, ref_index, None, "missing_live_trade", ref_row, None))
            continue
        matched_observed.add(observed_index)
        matched_count += 1
        obs_row = observed.loc[observed_index]
        row_classes: list[str] = ["matched_trade"]
        entry_delta_seconds = abs((obs_row["timestamp_utc"] - ref_row["timestamp_utc"]).total_seconds())
        exit_delta_seconds = abs((obs_row["exit_timestamp_utc"] - ref_row["exit_timestamp_utc"]).total_seconds())
        entry_delta_pips = abs(float(obs_row["entry_price"]) - float(ref_row["entry_price"])) * 10000.0
        exit_delta_pips = abs(float(obs_row["exit_price"]) - float(ref_row["exit_price"])) * 10000.0
        size_delta = abs(float(obs_row.get("position_size_lots", 0.0)) - float(ref_row.get("position_size_lots", 0.0)))
        if entry_delta_seconds > timestamp_tolerance:
            row_classes.append("entry_time_delta")
        if exit_delta_seconds > exit_tolerance:
            row_classes.append("exit_time_delta")
        if entry_delta_pips > fill_tolerance:
            row_classes.append("entry_price_delta")
            row_classes.append("spread_slippage_delta")
        if exit_delta_pips > price_tolerance:
            row_classes.append("exit_price_delta")
            row_classes.append("spread_slippage_delta")
        if size_delta > 0.000001:
            row_classes.append("size_delta")
        if str(obs_row.get("exit_reason", "")) != str(ref_row.get("exit_reason", "")):
            row_classes.append("stop_target_timeout_path_delta")
        for classification in set(row_classes):
            _increment(classifications, classification)
        if len(set(row_classes) - {"matched_trade"}) > 0:
            material_mismatch_count += 1
        rows.append(
            _diff_row(
                reference_name,
                observed_name,
                ref_index,
                observed_index,
                "|".join(sorted(set(row_classes))),
                ref_row,
                obs_row,
            )
        )

    for observed_index, obs_row in observed.iterrows():
        if observed_index in matched_observed:
            continue
        _increment(classifications, "extra_live_trade")
        rows.append(_diff_row(reference_name, observed_name, None, observed_index, "extra_live_trade", None, obs_row))

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame.from_records(rows).to_csv(output_csv, index=False)
    reference_pnl = float(reference["pnl_pips"].sum()) if "pnl_pips" in reference.columns else 0.0
    observed_pnl = float(observed["pnl_pips"].sum()) if "pnl_pips" in observed.columns else 0.0
    return TradeDiffSummary(
        reference_name=reference_name,
        observed_name=observed_name,
        matched_count=matched_count,
        missing_observed_count=int(classifications.get("missing_live_trade", 0)),
        extra_observed_count=int(classifications.get("extra_live_trade", 0)),
        material_mismatch_count=material_mismatch_count,
        pnl_delta_pips=round(observed_pnl - reference_pnl, 6),
        classifications=classifications,
        diff_csv_path=output_csv,
    )


def parse_tester_report_trade_count(tester_report_path: Path | None) -> int | None:
    if tester_report_path is None or not tester_report_path.exists():
        return None
    payload = _read_text_lossy(tester_report_path)
    if not payload:
        return None
    patterns = (
        r"Total Trades:</td>\s*<td[^>]*><b>(\d+)</b>",
        r"Total Trades\s*</[^>]+>\s*<[^>]+>\s*(?:<b>)?(\d+)",
        r"Total Trades\s+(\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, payload, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    text = html.unescape(re.sub(r"<[^>]+>", " ", payload))
    match = re.search(r"Total Trades\s+(\d+)", re.sub(r"\s+", " ", text), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def candidate_validation_suspended(candidate_id: str, settings: Settings) -> bool:
    incidents_dir = settings.paths().incidents_dir
    latest_paths = [incidents_dir / candidate_id / "latest_incident_report.json"]
    if incidents_dir.exists():
        latest_paths.extend(
            path for path in incidents_dir.glob("*/latest_incident_report.json") if path != latest_paths[0]
        )
    suspended_ids = {candidate_id}
    for latest_path in latest_paths:
        if not latest_path.exists():
            continue
        try:
            payload = read_json(latest_path)
        except Exception:
            continue
        if not bool(payload.get("validation_suspended")) or payload.get("workflow_status") == "decision_ready":
            continue
        blocked_ids = set(payload.get("blocked_candidate_ids") or [])
        blocked_ids.add(str(payload.get("candidate_id") or ""))
        if suspended_ids.intersection(blocked_ids):
            return True
    return False


def _freeze_artifacts(settings: Settings, candidate_id: str, *, live_audit_path: Path | None) -> FrozenArtifactSnapshot:
    report_dir = settings.paths().reports_dir / candidate_id
    artifact_paths: dict[str, str] = {}
    artifact_hashes: dict[str, str] = {}
    for name in (
        "strategy_spec.json",
        "review_packet.json",
        "forward_stage_report.json",
        "ea_spec.json",
        "rule_spec.json",
        "operational_status.md",
    ):
        path = report_dir / name
        if path.exists():
            artifact_paths[name] = str(path)
            artifact_hashes[name] = _sha256_file(path)
    latest_run = _latest_candidate_run_dir(settings, candidate_id)
    if latest_run is not None:
        artifact_paths["latest_mt5_run_dir"] = str(latest_run)
        for candidate in latest_run.glob("*"):
            if candidate.is_file() and candidate.suffix.lower() in {
                ".mq5",
                ".ex5",
                ".set",
                ".ini",
                ".json",
                ".csv",
                ".htm",
                ".html",
            }:
                artifact_hashes[f"latest_mt5_run/{candidate.name}"] = _sha256_file(candidate)
    if live_audit_path is not None and live_audit_path.exists():
        artifact_paths["live_audit_csv_path"] = str(live_audit_path)
        artifact_hashes["live_audit_csv"] = _sha256_file(live_audit_path)
    strategy_context = _strategy_context(report_dir)
    return FrozenArtifactSnapshot(
        candidate_id=candidate_id,
        artifact_paths=artifact_paths,
        artifact_hashes=artifact_hashes,
        live_audit_csv_path=live_audit_path,
        terminal_context=_terminal_context(settings),
        strategy_context=strategy_context,
        known_uptime_gaps=["AF-CAND-0320 terminal/client closed; do not use its live-demo state as viable evidence."],
    )


def _build_harness_check(
    settings: Settings, candidate_id: str, baseline_tester_report: Path | None
) -> TesterHarnessCheck:
    defaults = _known_good_window_defaults(settings, candidate_id)
    expected_min_trade_count = int(defaults.get("expected_min_trade_count", 1))
    observed_trade_count = parse_tester_report_trade_count(baseline_tester_report)
    if baseline_tester_report is None:
        status = "not_checked"
        notes = ["No repaired baseline replay report was supplied; command-line MT5 harness remains untrusted."]
    elif observed_trade_count is None:
        status = "failed"
        notes = ["Baseline tester report could not be parsed for Total Trades."]
    elif observed_trade_count < expected_min_trade_count:
        status = "failed"
        notes = [
            f"Baseline replay produced {observed_trade_count} trades below required minimum {expected_min_trade_count}."
        ]
    else:
        status = "passed"
        notes = ["Baseline known-good replay reproduced a nonzero/acceptable trade count."]
    return TesterHarnessCheck(
        status=status,  # type: ignore[arg-type]
        baseline_window_start=defaults.get("baseline_window_start"),
        baseline_window_end=defaults.get("baseline_window_end"),
        expected_min_trade_count=expected_min_trade_count,
        observed_trade_count=observed_trade_count,
        tester_report_path=baseline_tester_report,
        notes=notes,
    )


def _known_good_window_defaults(settings: Settings, candidate_id: str) -> dict[str, Any]:
    report_dir = settings.paths().reports_dir / candidate_id
    spec_path = report_dir / "strategy_spec.json"
    if spec_path.exists():
        try:
            spec_payload = read_json(spec_path)
            validation_profile = spec_payload.get("validation_profile") or {}
            configured_start = validation_profile.get("incident_baseline_window_start")
            configured_end = validation_profile.get("incident_baseline_window_end")
            configured_min_trades = validation_profile.get("incident_baseline_expected_min_trade_count")
            if configured_start or configured_end or configured_min_trades is not None:
                return {
                    "baseline_window_start": configured_start,
                    "baseline_window_end": configured_end,
                    "expected_min_trade_count": int(configured_min_trades or 1),
                }
        except Exception:
            pass
    return DEFAULT_KNOWN_GOOD_WINDOWS.get(candidate_id, {})


def _summarize_ledger(source_name: str, csv_path: Path) -> LedgerPerformanceSummary:
    frame = _load_trade_ledger(csv_path)
    if frame.empty or "pnl_pips" not in frame.columns:
        return LedgerPerformanceSummary(source_name=source_name, csv_path=csv_path)
    pnl = pd.to_numeric(frame["pnl_pips"], errors="coerce").fillna(0.0)
    gross_profit = float(pnl[pnl > 0].sum())
    gross_loss = float(abs(pnl[pnl < 0].sum()))
    profit_factor = None if gross_loss == 0.0 else gross_profit / gross_loss
    win_rate = None if len(pnl) == 0 else float((pnl > 0).mean())
    return LedgerPerformanceSummary(
        source_name=source_name,
        trade_count=int(len(pnl)),
        net_pips=round(float(pnl.sum()), 6),
        gross_profit_pips=round(gross_profit, 6),
        gross_loss_pips=round(gross_loss, 6),
        profit_factor=round(profit_factor, 6) if profit_factor is not None else None,
        win_rate=round(win_rate, 6) if win_rate is not None else None,
        csv_path=csv_path,
    )


def _attribute_incident(
    *,
    harness_check: TesterHarnessCheck,
    ledger_summaries: list[LedgerPerformanceSummary],
    trade_diff_summaries: list[TradeDiffSummary],
    has_mt5_replay: bool,
) -> ProductionIncidentAttributionBucket:
    if harness_check.status != "passed":
        return "harness_failure"
    mt5_summary = next((item for item in ledger_summaries if item.source_name == "mt5_replay_audit"), None)
    live_summary = next((item for item in ledger_summaries if item.source_name == "live_audit"), None)
    live_diff = next((item for item in trade_diff_summaries if item.reference_name == "mt5_replay_audit"), None)
    if has_mt5_replay and mt5_summary is not None and live_summary is not None and live_diff is not None:
        if mt5_summary.net_pips < 0 and live_diff.missing_observed_count == 0 and live_diff.extra_observed_count == 0:
            return "market_or_regime"
        if live_diff.missing_observed_count > 0 or live_diff.extra_observed_count > 0:
            return "implementation_delta"
        if live_diff.material_mismatch_count > 0 or live_summary.net_pips < mt5_summary.net_pips:
            return "execution_delta"
    return "unclassified"


def _workflow_status(
    *,
    harness_check: TesterHarnessCheck,
    has_replay: bool,
    has_diff: bool,
    attribution_bucket: ProductionIncidentAttributionBucket,
) -> ProductionIncidentStatus:
    if harness_check.status != "passed":
        return "harness_untrusted"
    if not has_replay:
        return "validation_suspended"
    if not has_diff:
        return "replay_ready"
    if attribution_bucket == "unclassified":
        return "diff_complete"
    return "attribution_complete"


def _load_trade_ledger(csv_path: Path) -> pd.DataFrame:
    if not csv_path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(csv_path)
    for column in ("timestamp_utc", "exit_timestamp_utc"):
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], utc=True, errors="coerce")
        else:
            frame[column] = pd.NaT
    for column in ("entry_price", "exit_price", "pnl_pips", "position_size_lots"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
        else:
            frame[column] = 0.0
    if "side" not in frame.columns:
        frame["side"] = ""
    if "exit_reason" not in frame.columns:
        frame["exit_reason"] = ""
    return frame.dropna(subset=["timestamp_utc"]).reset_index(drop=True)


def _best_match(
    reference_row: pd.Series, observed: pd.DataFrame, matched_observed: set[int], tolerance_seconds: int
) -> int | None:
    best_index: int | None = None
    best_delta: float | None = None
    for observed_index, observed_row in observed.iterrows():
        if observed_index in matched_observed:
            continue
        if str(reference_row.get("side", "")) != str(observed_row.get("side", "")):
            continue
        delta = abs((observed_row["timestamp_utc"] - reference_row["timestamp_utc"]).total_seconds())
        if delta > tolerance_seconds:
            continue
        if best_delta is None or delta < best_delta:
            best_index = int(observed_index)
            best_delta = float(delta)
    return best_index


def _diff_row(
    reference_name: str,
    observed_name: str,
    reference_index: int | None,
    observed_index: int | None,
    classification: str,
    reference_row: pd.Series | None,
    observed_row: pd.Series | None,
) -> dict[str, Any]:
    return {
        "reference_name": reference_name,
        "observed_name": observed_name,
        "reference_index": reference_index,
        "observed_index": observed_index,
        "classification": classification,
        "reference_entry_utc": _row_value(reference_row, "timestamp_utc"),
        "observed_entry_utc": _row_value(observed_row, "timestamp_utc"),
        "reference_exit_utc": _row_value(reference_row, "exit_timestamp_utc"),
        "observed_exit_utc": _row_value(observed_row, "exit_timestamp_utc"),
        "reference_side": _row_value(reference_row, "side"),
        "observed_side": _row_value(observed_row, "side"),
        "reference_entry_price": _row_value(reference_row, "entry_price"),
        "observed_entry_price": _row_value(observed_row, "entry_price"),
        "reference_exit_price": _row_value(reference_row, "exit_price"),
        "observed_exit_price": _row_value(observed_row, "exit_price"),
        "reference_pnl_pips": _row_value(reference_row, "pnl_pips"),
        "observed_pnl_pips": _row_value(observed_row, "pnl_pips"),
        "reference_exit_reason": _row_value(reference_row, "exit_reason"),
        "observed_exit_reason": _row_value(observed_row, "exit_reason"),
        "reference_lots": _row_value(reference_row, "position_size_lots"),
        "observed_lots": _row_value(observed_row, "position_size_lots"),
    }


def _row_value(row: pd.Series | None, column: str) -> Any:
    if row is None:
        return None
    value = row.get(column)
    if pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return value


def _increment(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _discover_latest_live_audit(candidate_id: str) -> Path | None:
    common_audit_dir = (
        Path.home() / "AppData" / "Roaming" / "MetaQuotes" / "Terminal" / "Common" / "Files" / "AgenticForex" / "Audit"
    )
    if not common_audit_dir.exists():
        return None
    matches = sorted(common_audit_dir.glob(f"{candidate_id}__*__audit.csv"), key=lambda path: path.stat().st_mtime)
    return matches[-1] if matches else None


def _latest_candidate_run_dir(settings: Settings, candidate_id: str) -> Path | None:
    run_root = settings.paths().mt5_runs_dir / candidate_id
    if not run_root.exists():
        return None
    runs = sorted((path for path in run_root.iterdir() if path.is_dir()), key=lambda path: path.stat().st_mtime)
    return runs[-1] if runs else None


def _strategy_context(report_dir: Path) -> dict[str, Any]:
    strategy_path = report_dir / "strategy_spec.json"
    if not strategy_path.exists():
        return {}
    try:
        payload = read_json(strategy_path)
    except Exception:
        return {}
    return {
        "candidate_id": payload.get("candidate_id"),
        "family": payload.get("family"),
        "entry_style": payload.get("entry_style"),
        "instrument": payload.get("instrument"),
        "execution_granularity": payload.get("execution_granularity"),
        "session_policy": payload.get("session_policy"),
        "account_model": payload.get("account_model"),
        "risk_envelope": payload.get("risk_envelope"),
    }


def _terminal_context(settings: Settings) -> dict[str, Any]:
    return {
        "configured_terminal_paths": list(settings.mt5_env.terminal_paths),
        "portable_mode": bool(settings.mt5_env.portable_mode),
        "tester_mode": settings.mt5_env.tester_mode,
        "parity_tester_mode": settings.mt5_env.parity_tester_mode,
        "live_trading_allowed_by_policy": bool(settings.mt5_env.allow_live_trading),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_text_lossy(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    encodings = ["utf-8", "cp1252", "latin-1"]
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings.insert(0, "utf-16")
    for encoding in encodings:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="ignore")


def _utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
