"""Tests for the industry report generation."""

from __future__ import annotations

import json
from pathlib import Path

from agentic_forex.industry.report import (
    IndustryReport,
    generate_industry_report,
    _escape_html,
    _md_body_to_html,
)


def test_generate_industry_report(tmp_path: Path, monkeypatch):
    """Industry report runs against a minimal project structure."""
    # Set up minimal project structure
    (tmp_path / "experiments").mkdir()
    exp_data = {"candidate_id": "AF-CAND-0001", "family": "test"}
    (tmp_path / "experiments" / "af-cand-0001_test_family_20260101T000000Z.json").write_text(
        json.dumps(exp_data)
    )

    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "AF-CAND-0001").mkdir()

    (tmp_path / "approvals").mkdir()
    approval_record = json.dumps({"candidate_id": "AF-CAND-0001", "action": "approved"})
    (tmp_path / "approvals" / "approval_log.jsonl").write_text(approval_record + "\n")

    (tmp_path / "data" / "corpus").mkdir(parents=True)
    (tmp_path / "data" / "corpus" / "sample.parquet").write_text("placeholder")

    (tmp_path / "Goblin").mkdir()
    (tmp_path / "Goblin" / "STATUS.md").write_text("# Status\nAll phases complete.\n")

    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "default.toml").write_text("")

    from agentic_forex.config import load_settings

    settings = load_settings(project_root=str(tmp_path))

    report = generate_industry_report(settings)

    assert isinstance(report, IndustryReport)
    assert report.generated_utc
    assert "Goblin Industry Update" in report.markdown
    assert "<html" in report.html
    assert len(report.sections) == 5

    # Verify files written
    md_path = Path(report.report_dir) / "latest.md"
    html_path = Path(report.report_dir) / "latest.html"
    assert md_path.exists()
    assert html_path.exists()


def test_escape_html():
    assert _escape_html("<script>alert('xss')</script>") == "&lt;script&gt;alert('xss')&lt;/script&gt;"
    assert _escape_html('a & b "c"') == 'a &amp; b &quot;c&quot;'


def test_md_body_to_html():
    body = "- **Total:** 5\n- `family_a`: 3"
    html = _md_body_to_html(body)
    assert "<ul>" in html
    assert "<strong>Total:</strong>" in html
    assert "<code>family_a</code>" in html


def test_report_model_serialization():
    """Report model round-trips through JSON."""
    from agentic_forex.industry.report import IndustryReportSection

    report = IndustryReport(
        generated_utc="2026-04-13T00:00:00Z",
        title="Test",
        sections=[IndustryReportSection(title="S1", body="content")],
        markdown="# Test",
        html="<html></html>",
        report_dir="/tmp/test",
    )
    data = json.loads(report.model_dump_json())
    assert data["title"] == "Test"
    assert len(data["sections"]) == 1
