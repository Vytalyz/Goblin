"""Tests for tools/holdout_access_ceremony.py (EX-4, G3/G7/G8/G9/G12)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import holdout_access_ceremony as hc  # noqa: E402


def _entry(decision_id: str) -> dict:
    return {"decision_id": decision_id, "phase": "ML-2.0"}


class TestCounters:
    def test_count_completed_zero(self):
        assert hc.count_completed_accesses([]) == 0

    def test_count_completed_one(self):
        e = [_entry("DEC-ML-HOLDOUT-ACCESS-1-INITIATED"), _entry("DEC-ML-HOLDOUT-ACCESS-1-COMPLETED")]
        assert hc.count_completed_accesses(e) == 1

    def test_count_aborted_one(self):
        e = [_entry("DEC-ML-HOLDOUT-ACCESS-1-INITIATED"), _entry("DEC-ML-HOLDOUT-ACCESS-1-ABORTED")]
        assert hc.count_aborted_accesses(e) == 1

    def test_unrelated_decisions_ignored(self):
        e = [_entry("DEC-ML-1.6.0-CANDIDATES"), _entry("DEC-ML-2.0-TARGET")]
        assert hc.count_completed_accesses(e) == 0
        assert hc.count_aborted_accesses(e) == 0


class TestRefusal:
    def test_proceed_when_no_history(self):
        assert hc.ceremony_should_refuse([]) is None

    def test_refuse_at_hard_cap_via_completed(self):
        e = [
            _entry("DEC-ML-HOLDOUT-ACCESS-1-INITIATED"),
            _entry("DEC-ML-HOLDOUT-ACCESS-1-COMPLETED"),
            _entry("DEC-ML-HOLDOUT-ACCESS-2-INITIATED"),
            _entry("DEC-ML-HOLDOUT-ACCESS-2-COMPLETED"),
        ]
        msg = hc.ceremony_should_refuse(e)
        assert msg is not None and "hard cap" in msg

    def test_refuse_at_hard_cap_via_mixed_completed_and_aborted(self):
        e = [
            _entry("DEC-ML-HOLDOUT-ACCESS-1-INITIATED"),
            _entry("DEC-ML-HOLDOUT-ACCESS-1-ABORTED"),
            _entry("DEC-ML-HOLDOUT-ACCESS-2-INITIATED"),
            _entry("DEC-ML-HOLDOUT-ACCESS-2-COMPLETED"),
        ]
        msg = hc.ceremony_should_refuse(e)
        assert msg is not None and "hard cap" in msg

    def test_refuse_on_dangling_initiated(self):
        e = [_entry("DEC-ML-HOLDOUT-ACCESS-1-INITIATED")]
        msg = hc.ceremony_should_refuse(e)
        assert msg is not None and "dangling" in msg.lower()

    def test_proceed_after_one_completed(self):
        e = [
            _entry("DEC-ML-HOLDOUT-ACCESS-1-INITIATED"),
            _entry("DEC-ML-HOLDOUT-ACCESS-1-COMPLETED"),
        ]
        assert hc.ceremony_should_refuse(e) is None


class TestNextAccessN:
    def test_first_run_is_one(self):
        assert hc.next_access_n([]) == 1

    def test_after_one_returns_two(self):
        e = [_entry("DEC-ML-HOLDOUT-ACCESS-1-INITIATED"), _entry("DEC-ML-HOLDOUT-ACCESS-1-COMPLETED")]
        assert hc.next_access_n(e) == 2

    def test_aborted_consumes_index(self):
        e = [_entry("DEC-ML-HOLDOUT-ACCESS-1-INITIATED"), _entry("DEC-ML-HOLDOUT-ACCESS-1-ABORTED")]
        assert hc.next_access_n(e) == 2


class TestKeyOutsideRepo:
    def test_key_inside_repo_rejected(self, tmp_path, monkeypatch):
        # Synthesize a key inside REPO_ROOT
        bad = REPO_ROOT / "tmp_should_not_exist.key"
        bad.write_text("x")
        try:
            with pytest.raises(RuntimeError, match="inside the repository"):
                hc._validate_key_outside_repo(bad)
        finally:
            bad.unlink(missing_ok=True)

    def test_key_outside_repo_accepted(self, tmp_path):
        outside_key = tmp_path / "ok.key"
        outside_key.write_text("x")
        # Should not raise
        hc._validate_key_outside_repo(outside_key)


class TestShredPlaintext:
    def test_shred_removes_file(self, tmp_path):
        p = tmp_path / "plain.bin"
        p.write_bytes(b"sensitive" * 100)
        assert p.exists()
        hc.shred_plaintext(p, passes=2)
        assert not p.exists()

    def test_shred_missing_file_noop(self, tmp_path):
        p = tmp_path / "nope.bin"
        hc.shred_plaintext(p)
        assert not p.exists()


class TestAppendDecision:
    def test_append_writes_one_line(self, tmp_path):
        log = tmp_path / "ml_decisions.jsonl"
        log.write_text("")
        hc.append_decision(log, {"decision_id": "TEST-1", "phase": "X"})
        hc.append_decision(log, {"decision_id": "TEST-2", "phase": "X"})
        lines = log.read_text().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["decision_id"] == "TEST-1"


class TestRunCeremonyEndToEnd:
    @pytest.fixture
    def fernet_setup(self, tmp_path):
        pytest.importorskip("cryptography")
        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        key_path = tmp_path / "test.key"
        key_path.write_bytes(key)
        sealed_path = tmp_path / "sealed.parquet.enc"
        sealed_path.write_bytes(Fernet(key).encrypt(b"PARQUET_PLAINTEXT_FAKE"))
        return key_path, sealed_path

    def test_success_writes_initiated_and_completed(self, tmp_path, fernet_setup):
        key_path, sealed = fernet_setup
        log = tmp_path / "ml_decisions.jsonl"
        log.write_text("")
        # Eval cmd: a python script that just exits 0 after reading file
        script = tmp_path / "noop_eval.py"
        script.write_text("import sys, pathlib\nassert pathlib.Path(sys.argv[1]).exists()\n")
        rc = hc.run_ceremony(
            key_path=key_path,
            eval_cmd=[sys.executable, str(script)],
            note="A" * 60,
            decisions_log=log,
            sealed_path=sealed,
        )
        assert rc == 0
        entries = [json.loads(line) for line in log.read_text().strip().splitlines()]
        ids = [e["decision_id"] for e in entries]
        assert "DEC-ML-HOLDOUT-ACCESS-1-INITIATED" in ids
        assert "DEC-ML-HOLDOUT-ACCESS-1-COMPLETED" in ids

    def test_eval_failure_writes_aborted(self, tmp_path, fernet_setup):
        key_path, sealed = fernet_setup
        log = tmp_path / "ml_decisions.jsonl"
        log.write_text("")
        script = tmp_path / "fail_eval.py"
        script.write_text("import sys; sys.exit(7)\n")
        rc = hc.run_ceremony(
            key_path=key_path,
            eval_cmd=[sys.executable, str(script)],
            note="B" * 60,
            decisions_log=log,
            sealed_path=sealed,
        )
        assert rc == 6
        entries = [json.loads(line) for line in log.read_text().strip().splitlines()]
        ids = [e["decision_id"] for e in entries]
        assert "DEC-ML-HOLDOUT-ACCESS-1-INITIATED" in ids
        assert "DEC-ML-HOLDOUT-ACCESS-1-ABORTED" in ids
        # And aborted counts toward cap.
        assert hc.count_aborted_accesses(entries) == 1

    def test_refuses_third_access(self, tmp_path, fernet_setup):
        key_path, sealed = fernet_setup
        log = tmp_path / "ml_decisions.jsonl"
        # Pre-seed two completed accesses.
        log.write_text(
            "\n".join(
                [
                    json.dumps({"decision_id": "DEC-ML-HOLDOUT-ACCESS-1-INITIATED"}),
                    json.dumps({"decision_id": "DEC-ML-HOLDOUT-ACCESS-1-COMPLETED"}),
                    json.dumps({"decision_id": "DEC-ML-HOLDOUT-ACCESS-2-INITIATED"}),
                    json.dumps({"decision_id": "DEC-ML-HOLDOUT-ACCESS-2-COMPLETED"}),
                ]
            )
            + "\n"
        )
        script = tmp_path / "noop_eval.py"
        script.write_text("import sys; sys.exit(0)\n")
        rc = hc.run_ceremony(
            key_path=key_path,
            eval_cmd=[sys.executable, str(script)],
            note="C" * 60,
            decisions_log=log,
            sealed_path=sealed,
        )
        assert rc == 5  # refused

    def test_short_note_rejected(self, tmp_path, fernet_setup):
        key_path, sealed = fernet_setup
        log = tmp_path / "ml_decisions.jsonl"
        log.write_text("")
        rc = hc.run_ceremony(
            key_path=key_path,
            eval_cmd=[sys.executable, "-c", "pass"],
            note="too short",
            decisions_log=log,
            sealed_path=sealed,
        )
        assert rc == 2
