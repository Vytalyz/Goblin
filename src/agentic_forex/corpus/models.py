from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class SourceQualityReport(BaseModel):
    source_id: str
    extraction_confidence: float
    relevance_score: float
    duplicate_group_id: str | None = None
    trust_band: str
    allowed_for_discovery: bool
    reasons: list[str] = Field(default_factory=list)
    copyright_signals: list[str] = Field(default_factory=list)
    front_matter_signals: list[str] = Field(default_factory=list)
    best_excerpt: str | None = None


class KnowledgeNote(BaseModel):
    source_id: str
    title: str
    note: str
    concept_tags: list[str] = Field(default_factory=list)
    family_relevance_tags: list[str] = Field(default_factory=list)


class StrategyClaim(BaseModel):
    source_id: str
    family: str
    claim: str
    confidence: float
    claim_type: Literal[
        "generic",
        "session_anchor",
        "holding_horizon",
        "overnight_rule",
        "momentum_event_decay",
        "risk_day_filter",
        "anti_pattern",
    ] = "generic"
    prior_effect: Literal["neutral", "support", "penalty", "veto"] = "neutral"
    concept_tags: list[str] = Field(default_factory=list)
    family_relevance_tags: list[str] = Field(default_factory=list)


class ContradictionRecord(BaseModel):
    family: str
    summary: str
    source_ids: list[str]


class CorpusCatalogEntry(BaseModel):
    source_id: str
    path: Path
    title: str
    file_type: str
    fingerprint: str
    size_bytes: int
    extraction_status: str
    metadata: dict = Field(default_factory=dict)
    quality_report: SourceQualityReport
    extracted_text_path: Path | None = None


class CorpusCatalog(BaseModel):
    mirror_path: Path
    entries: list[CorpusCatalogEntry]


class CorpusDigest(BaseModel):
    candidate_family: str
    source_citations: list[str]
    highlights: list[str]
    contradictions: list[str]
    approved_source_ids: list[str] = Field(default_factory=list)
    quarantined_source_ids: list[str] = Field(default_factory=list)
    source_notes: list[KnowledgeNote] = Field(default_factory=list)
    strategy_claims: list[StrategyClaim] = Field(default_factory=list)
    contradiction_records: list[ContradictionRecord] = Field(default_factory=list)
    copyright_signals: dict[str, list[str]] = Field(default_factory=dict)
    book_prior_source_ids: list[str] = Field(default_factory=list)
    typed_claim_counts: dict[str, int] = Field(default_factory=dict)
    quality_summary: dict = Field(default_factory=dict)
