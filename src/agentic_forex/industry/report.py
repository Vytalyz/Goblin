"""Generate industry update reports from local corpus and experiment data.

Produces Markdown and HTML reports summarizing:
- Active experiment families and their current status
- Candidate pipeline health (total, approved, pending, rejected)
- Recent experiment results and trends
- Corpus coverage summary
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from agentic_forex.config import GoblinConfig


class IndustryReportSection(BaseModel):
    title: str
    body: str


class IndustryReport(BaseModel):
    generated_utc: str
    title: str
    sections: list[IndustryReportSection]
    markdown: str
    html: str
    report_dir: str


def generate_industry_report(settings: GoblinConfig) -> IndustryReport:
    """Build an industry update report from local data sources."""
    generated = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    paths = settings.paths()
    sections: list[IndustryReportSection] = []

    # ── Section 1: Experiment Pipeline ──
    experiments_dir = paths.experiments_dir
    experiment_files = sorted(experiments_dir.glob("*.json")) if experiments_dir.exists() else []
    families: dict[str, int] = {}
    for ef in experiment_files:
        name = ef.stem
        parts = name.split("_", 1)
        if len(parts) > 1:
            # Extract family hint from filename pattern: af-cand-NNNN_family_timestamp
            family_parts = parts[1].rsplit("_", 1)
            family_name = family_parts[0] if len(family_parts) > 1 else parts[1]
            families[family_name] = families.get(family_name, 0) + 1

    pipeline_lines = [
        f"- **Total experiment files:** {len(experiment_files)}",
        f"- **Distinct families:** {len(families)}",
    ]
    for family, count in sorted(families.items(), key=lambda x: -x[1])[:10]:
        pipeline_lines.append(f"  - `{family}`: {count} experiments")

    sections.append(
        IndustryReportSection(
            title="Experiment Pipeline",
            body="\n".join(pipeline_lines),
        )
    )

    # ── Section 2: Candidate Reports ──
    reports_dir = paths.root / "reports"
    candidate_dirs = []
    if reports_dir.exists():
        candidate_dirs = [d for d in sorted(reports_dir.iterdir()) if d.is_dir() and d.name.startswith("AF-CAND-")]

    sections.append(
        IndustryReportSection(
            title="Candidate Portfolio",
            body=f"- **Total candidate report directories:** {len(candidate_dirs)}",
        )
    )

    # ── Section 3: Approval Activity ──
    approval_log = paths.root / "approvals" / "approval_log.jsonl"
    approval_count = 0
    recent_approvals: list[str] = []
    if approval_log.exists():
        lines = approval_log.read_text(encoding="utf-8").strip().splitlines()
        approval_count = len(lines)
        for line in lines[-5:]:
            try:
                record = json.loads(line)
                cid = record.get("candidate_id", "unknown")
                action = record.get("action", "unknown")
                recent_approvals.append(f"  - `{cid}`: {action}")
            except (json.JSONDecodeError, KeyError):
                pass

    approval_lines = [f"- **Total approval records:** {approval_count}"]
    if recent_approvals:
        approval_lines.append("- **Recent approvals:**")
        approval_lines.extend(recent_approvals)

    sections.append(
        IndustryReportSection(
            title="Approval Activity",
            body="\n".join(approval_lines),
        )
    )

    # ── Section 4: Data Corpus ──
    corpus_dir = paths.root / "data" / "corpus"
    corpus_files = list(corpus_dir.rglob("*")) if corpus_dir.exists() else []
    corpus_file_count = sum(1 for f in corpus_files if f.is_file())

    sections.append(
        IndustryReportSection(
            title="Data Corpus",
            body=f"- **Corpus files:** {corpus_file_count}",
        )
    )

    # ── Section 5: Goblin Program Status ──
    status_file = paths.root / "Goblin" / "STATUS.md"
    status_summary = "Status file not found."
    if status_file.exists():
        # Extract first non-empty, non-heading line as summary
        for line in status_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                status_summary = stripped
                break

    sections.append(
        IndustryReportSection(
            title="Goblin Program Status",
            body=f"- {status_summary}",
        )
    )

    # ── Build Markdown ──
    md_parts = [
        "# Goblin Industry Update",
        "",
        f"**Generated:** {generated}",
        "",
    ]
    for section in sections:
        md_parts.append(f"## {section.title}")
        md_parts.append("")
        md_parts.append(section.body)
        md_parts.append("")

    markdown = "\n".join(md_parts)

    # ── Build HTML ──
    html = _render_html(generated, sections)

    # ── Write outputs ──
    report_dir = paths.root / "reports" / "industry-update"
    report_dir.mkdir(parents=True, exist_ok=True)

    md_path = report_dir / "latest.md"
    md_path.write_text(markdown, encoding="utf-8")

    html_path = report_dir / "latest.html"
    html_path.write_text(html, encoding="utf-8")

    return IndustryReport(
        generated_utc=generated,
        title="Goblin Industry Update",
        sections=sections,
        markdown=markdown,
        html=html,
        report_dir=str(report_dir),
    )


def _render_html(generated: str, sections: list[IndustryReportSection]) -> str:
    """Render a self-contained HTML report without external dependencies."""
    section_html_parts = []
    for section in sections:
        # Convert markdown-style bullets to HTML
        body_html = _md_body_to_html(section.body)
        section_html_parts.append(f"<section><h2>{_escape_html(section.title)}</h2>{body_html}</section>")
    sections_html = "\n".join(section_html_parts)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Goblin Industry Update</title>
<style>
  body {{ font-family: system-ui, -apple-system, sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }}
  h1 {{ border-bottom: 2px solid #2563eb; padding-bottom: 0.5rem; }}
  h2 {{ color: #2563eb; margin-top: 2rem; }}
  .meta {{ color: #666; font-size: 0.9rem; }}
  code {{ background: #f1f5f9; padding: 0.1em 0.3em; border-radius: 3px; font-size: 0.9em; }}
  ul {{ padding-left: 1.5rem; }}
  li {{ margin: 0.3rem 0; }}
  section {{ margin-bottom: 1.5rem; }}
</style>
</head>
<body>
<h1>Goblin Industry Update</h1>
<p class="meta">Generated: {_escape_html(generated)}</p>
{sections_html}
</body>
</html>"""


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _md_body_to_html(body: str) -> str:
    """Convert simple markdown bullet lists to HTML."""
    lines = body.split("\n")
    html_parts: list[str] = []
    in_list = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- "):
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            content = stripped[2:]
            # Convert **bold** and `code`
            content = _inline_md_to_html(content)
            html_parts.append(f"<li>{content}</li>")
        elif stripped.startswith("  - "):
            content = stripped[4:]
            content = _inline_md_to_html(content)
            html_parts.append(f"<li style='margin-left:1rem'>{content}</li>")
        else:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            if stripped:
                html_parts.append(f"<p>{_inline_md_to_html(stripped)}</p>")

    if in_list:
        html_parts.append("</ul>")

    return "\n".join(html_parts)


def _inline_md_to_html(text: str) -> str:
    """Convert inline markdown (bold, code) to HTML."""
    import re

    # Bold: **text**
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Code: `text`
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text
