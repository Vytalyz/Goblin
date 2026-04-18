from __future__ import annotations

from pathlib import Path

from conftest import create_book_prior_file, create_corpus_mirror, scaffold_project

from agentic_forex.config import load_settings
from agentic_forex.corpus.catalog import build_digest, catalog_corpus
from agentic_forex.runtime.security import ReadPolicy


def test_catalog_corpus_includes_supplemental_book_and_emits_typed_claims(tmp_path: Path):
    project_root = scaffold_project(tmp_path / "Agentic Forex Corpus")
    mirror = create_corpus_mirror(tmp_path)
    book_path = create_book_prior_file(tmp_path)
    override_path = tmp_path / "book-override.toml"
    override_path.write_text(
        f"[data]\nsupplemental_source_paths = ['{book_path.as_posix()}']\n",
        encoding="utf-8",
    )
    settings = load_settings(project_root=project_root, config_path=override_path)
    read_policy = ReadPolicy(
        project_root=settings.project_root,
        allowed_external_roots=[mirror, book_path.parent],
    )

    catalog = catalog_corpus(mirror, settings, read_policy)
    digest = build_digest(family="day_trading", settings=settings, max_sources=6)

    assert any(entry.path.resolve() == book_path.resolve() for entry in catalog.entries)
    assert digest.book_prior_source_ids
    claim_types = {
        claim.claim_type for claim in digest.strategy_claims if claim.source_id in digest.book_prior_source_ids
    }
    assert {
        "session_anchor",
        "holding_horizon",
        "overnight_rule",
        "momentum_event_decay",
        "risk_day_filter",
        "anti_pattern",
    }.issubset(claim_types)
