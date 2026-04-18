from __future__ import annotations

import hashlib
import re
from pathlib import Path

from agentic_forex.config import Settings
from agentic_forex.corpus.models import (
    ContradictionRecord,
    CorpusCatalog,
    CorpusCatalogEntry,
    CorpusDigest,
    KnowledgeNote,
    SourceQualityReport,
    StrategyClaim,
)
from agentic_forex.runtime.security import ReadPolicy
from agentic_forex.utils.io import read_json, write_json

SUPPORTED_SUFFIXES = {".txt", ".pdf", ".epub"}
TRUST_KEYWORDS = {
    "high": ["playbook", "guide", "research", "manual"],
    "medium": ["notes", "journal", "handbook"],
}
COPYRIGHT_PATTERNS = [
    r"\bcopyright\b",
    r"\ball rights reserved\b",
    r"no part of this publication",
    r"may not be reproduced",
    r"published by",
    r"library of congress",
    r"\bisbn\b",
    r"mcgraw-hill",
    r"wiley",
]
FRONT_MATTER_PATTERNS = [
    r"\btable of contents\b",
    r"^contents$",
    r"\bforeword\b",
    r"\bpreface\b",
    r"\backnowledg",
    r"\babout the author\b",
    r"\bdedication\b",
    r"\bintroduction\b",
    r"\bglossary\b",
    r"\bindex\b",
]
GENERAL_CONTENT_KEYWORDS = {
    "entry": 0.4,
    "entries": 0.4,
    "exit": 0.35,
    "stop": 0.3,
    "target": 0.3,
    "risk": 0.2,
    "session": 0.25,
    "intraday": 0.25,
    "price action": 0.3,
    "trend": 0.25,
    "breakout": 0.35,
    "momentum": 0.3,
    "pullback": 0.3,
    "mean reversion": 0.35,
    "fade": 0.3,
    "setup": 0.25,
    "trade": 0.15,
    "trading": 0.15,
    "forex": 0.15,
    "currency": 0.15,
}
FAMILY_KEYWORDS = {
    "scalping": {
        "scalp": 0.4,
        "scalping": 0.4,
        "intraday": 0.25,
        "5-minute": 0.2,
        "5 minute": 0.2,
        "breakout": 0.3,
        "momentum": 0.3,
        "pullback": 0.25,
        "mean reversion": 0.25,
        "session": 0.2,
        "price action": 0.25,
    },
    "day_trading": {
        "day trading": 0.4,
        "session": 0.3,
        "breakout": 0.3,
        "range": 0.2,
        "intraday": 0.25,
        "trend": 0.2,
        "momentum": 0.2,
    },
}


def catalog_corpus(mirror_path: Path, settings: Settings, read_policy: ReadPolicy) -> CorpusCatalog:
    mirror = read_policy.assert_allowed(mirror_path)
    metadata = _load_metadata(mirror, read_policy)
    extracted_dir = settings.paths().corpus_extracted_dir
    entries: list[CorpusCatalogEntry] = []
    fingerprint_groups: dict[str, list[str]] = {}
    for file_path in _catalog_source_files(mirror, settings, read_policy):
        if file_path.name in {"_info.json", "_info.text", "Trading.txt"}:
            continue
        suffix = file_path.suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            continue
        fingerprint = _fingerprint(file_path)
        source_id = f"SRC-{len(entries) + 1:03d}"
        title = file_path.stem
        metadata_payload = metadata.get(title.lower(), {}) if file_path.is_relative_to(mirror) else {}
        extracted_text_path = extracted_dir / f"{fingerprint}.txt"
        text, status = extract_text(file_path, extracted_text_path, read_policy)
        if text:
            extracted_text_path.write_text(text, encoding="utf-8")
        else:
            extracted_text_path = None
        fingerprint_groups.setdefault(fingerprint, []).append(source_id)
        quality_report = _quality_report(
            source_id=source_id,
            title=title,
            text=text,
            metadata=metadata_payload,
            extraction_status=status,
            settings=settings,
        )
        entries.append(
            CorpusCatalogEntry(
                source_id=source_id,
                path=file_path,
                title=title,
                file_type=suffix.lstrip("."),
                fingerprint=fingerprint,
                size_bytes=file_path.stat().st_size,
                extraction_status=status,
                metadata=metadata_payload,
                quality_report=quality_report,
                extracted_text_path=extracted_text_path,
            )
        )
    updated_entries = [_apply_duplicate_group(entry, fingerprint_groups) for entry in entries]
    catalog = CorpusCatalog(mirror_path=mirror, entries=updated_entries)
    write_json(settings.catalog_path, catalog.model_dump(mode="json"))
    _write_quality_side_artifacts(catalog, settings)
    return catalog


def build_digest(
    *,
    family: str,
    settings: Settings,
    max_sources: int = 5,
) -> CorpusDigest:
    catalog = CorpusCatalog.model_validate(read_json(settings.catalog_path))
    approved = [entry for entry in catalog.entries if entry.quality_report.allowed_for_discovery]
    approved = sorted(
        approved,
        key=lambda entry: (entry.quality_report.relevance_score, entry.quality_report.extraction_confidence),
        reverse=True,
    )
    family_selected = [entry for entry in approved if _family_relevance(entry, family) > 0][:max_sources]
    if not family_selected:
        family_selected = approved[:max_sources]
    quarantined = [entry.source_id for entry in catalog.entries if not entry.quality_report.allowed_for_discovery]
    notes = [_build_knowledge_note(entry, family) for entry in family_selected]
    claims = _build_strategy_claims(family_selected, family)
    contradiction_records = _build_contradictions(family_selected, family)
    highlights = [note.note for note in notes]
    typed_claim_counts: dict[str, int] = {}
    for claim in claims:
        typed_claim_counts[claim.claim_type] = typed_claim_counts.get(claim.claim_type, 0) + 1
    copyright_signals = {
        entry.source_id: entry.quality_report.copyright_signals
        for entry in family_selected
        if entry.quality_report.copyright_signals
    }
    return CorpusDigest(
        candidate_family=family,
        source_citations=[entry.source_id for entry in family_selected],
        highlights=highlights,
        contradictions=[item.summary for item in contradiction_records],
        approved_source_ids=[entry.source_id for entry in family_selected],
        quarantined_source_ids=quarantined,
        source_notes=notes,
        strategy_claims=claims,
        contradiction_records=contradiction_records,
        copyright_signals=copyright_signals,
        book_prior_source_ids=[entry.source_id for entry in family_selected if _is_book_prior_entry(entry)],
        typed_claim_counts=typed_claim_counts,
        quality_summary={
            "catalog_size": len(catalog.entries),
            "approved_count": len(approved),
            "quarantined_count": len(quarantined),
        },
    )


def extract_text(file_path: Path, output_path: Path, read_policy: ReadPolicy) -> tuple[str, str]:
    source = read_policy.assert_allowed(file_path)
    suffix = source.suffix.lower()
    try:
        if suffix == ".txt":
            return source.read_text(encoding="utf-8"), "extracted"
        if suffix == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(str(source))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            return text, "extracted"
        if suffix == ".epub":
            from ebooklib import epub

            book = epub.read_epub(str(source))
            chunks: list[str] = []
            for item in book.get_items():
                if item.get_type() == 9:
                    body = item.get_content().decode("utf-8", errors="ignore")
                    chunks.append(re.sub(r"<[^>]+>", " ", body))
            return "\n".join(chunks), "extracted"
        return "", "unsupported"
    except Exception:
        return "", "extraction_failed"


def _fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _quality_report(
    *,
    source_id: str,
    title: str,
    text: str,
    metadata: dict,
    extraction_status: str,
    settings: Settings,
) -> SourceQualityReport:
    extraction_confidence = 1.0 if extraction_status == "extracted" and text.strip() else 0.1
    copyright_signals = _collect_flagged_chunks(text, COPYRIGHT_PATTERNS)
    front_matter_signals = _collect_flagged_chunks(text, FRONT_MATTER_PATTERNS)
    best_excerpt = _best_overall_excerpt(title, text)
    relevance_score = _relevance_score(title, text)
    reasons: list[str] = []
    trust_band = _trust_band(title, metadata)
    allowed_for_discovery = True
    if extraction_confidence < settings.data.extraction_confidence_floor:
        reasons.append("Extraction confidence below discovery floor.")
        allowed_for_discovery = False
    if relevance_score < settings.data.discovery_relevance_floor:
        reasons.append("Relevance score below discovery floor.")
        allowed_for_discovery = False
    return SourceQualityReport(
        source_id=source_id,
        extraction_confidence=round(extraction_confidence, 3),
        relevance_score=round(relevance_score, 3),
        duplicate_group_id=None,
        trust_band=trust_band,
        allowed_for_discovery=allowed_for_discovery,
        reasons=reasons,
        copyright_signals=copyright_signals,
        front_matter_signals=front_matter_signals,
        best_excerpt=best_excerpt,
    )


def _relevance_score(title: str, text: str) -> float:
    haystack = f"{title} {text}".lower()
    score = 0.2
    for keyword, weight in GENERAL_CONTENT_KEYWORDS.items():
        if keyword in haystack:
            score += weight
    best_scalping = _excerpt_score(_best_excerpt(title, text, "scalping"), "scalping")
    best_day = _excerpt_score(_best_excerpt(title, text, "day_trading"), "day_trading")
    score += max(best_scalping, best_day) * 0.25
    return min(score, 1.0)


def _trust_band(title: str, metadata: dict) -> str:
    lowered = title.lower()
    rating = metadata.get("rating")
    if isinstance(rating, (int, float)) and rating >= 4:
        return "high"
    if any(token in lowered for token in TRUST_KEYWORDS["high"]):
        return "high"
    if any(token in lowered for token in TRUST_KEYWORDS["medium"]):
        return "medium"
    return "medium" if metadata else "low"


def _apply_duplicate_group(entry: CorpusCatalogEntry, fingerprint_groups: dict[str, list[str]]) -> CorpusCatalogEntry:
    duplicates = fingerprint_groups.get(entry.fingerprint, [])
    if len(duplicates) <= 1:
        return entry
    quality = entry.quality_report.model_copy(
        update={
            "duplicate_group_id": entry.fingerprint[:12],
            "allowed_for_discovery": False,
            "reasons": entry.quality_report.reasons + ["Duplicate content fingerprint."],
        }
    )
    return entry.model_copy(update={"quality_report": quality})


def _family_relevance(entry: CorpusCatalogEntry, family: str) -> float:
    excerpt = _entry_best_excerpt(entry, family)
    return _excerpt_score(excerpt, family)


def _build_knowledge_note(entry: CorpusCatalogEntry, family: str) -> KnowledgeNote:
    preview = _entry_best_excerpt(entry, family)
    tags = [family.replace("_", "-")]
    lowered = preview.lower()
    if "intraday" in lowered or "session" in lowered:
        tags.append("intraday")
    if "breakout" in lowered or "momentum" in lowered:
        tags.append("breakout")
    if "mean reversion" in lowered or "fade" in lowered or "pullback" in lowered:
        tags.append("mean-reversion")
    if "copyright" in lowered:
        tags.append("copyright-flagged")
    return KnowledgeNote(
        source_id=entry.source_id,
        title=entry.title,
        note=f"{entry.source_id}: {preview}",
        concept_tags=tags,
        family_relevance_tags=[family],
    )


def _build_strategy_claims(entries: list[CorpusCatalogEntry], family: str) -> list[StrategyClaim]:
    claims: list[StrategyClaim] = []
    for entry in entries:
        text = _entry_text(entry)
        typed_claims = _extract_typed_claims(entry, family, text)
        if typed_claims:
            claims.extend(typed_claims)
            continue
        preview = _entry_best_excerpt(entry, family).lower()
        if family == "scalping":
            if any(token in preview for token in ("breakout", "momentum", "continuation", "trend")):
                claim_text = "Exploit Europe-session directional expansion after momentum and price-location alignment."
            elif any(token in preview for token in ("fade", "mean reversion", "pullback", "exhaustion")):
                claim_text = "Fade stretched intraday movement only after clear exhaustion and reversal confirmation."
            else:
                claim_text = "Trade high-quality intraday structure with explicit spread and volatility filters."
        else:
            claim_text = "Trade session-defined directional expansion with disciplined time exits."
        claims.append(
            StrategyClaim(
                source_id=entry.source_id,
                family=family,
                claim=claim_text,
                confidence=entry.quality_report.relevance_score,
                claim_type="generic",
                prior_effect="neutral",
                concept_tags=[family.replace("_", "-")],
                family_relevance_tags=[family],
            )
        )
    return claims


def _build_contradictions(entries: list[CorpusCatalogEntry], family: str) -> list[ContradictionRecord]:
    if not entries:
        return []
    if family != "scalping":
        summary = "Approved sources disagree on whether session breakouts should be concentrated around one opening window or traded across broader intraday continuation."
        return [ContradictionRecord(family=family, summary=summary, source_ids=[entry.source_id for entry in entries])]

    claim_styles = {_infer_claim_style(_entry_best_excerpt(entry, family)) for entry in entries}
    if {"breakout", "fade"}.issubset(claim_styles):
        summary = "Approved scalping sources split between Europe-session momentum breakout tactics and short-term exhaustion fades."
    elif "breakout" in claim_styles:
        summary = "Approved scalping sources broadly support momentum or breakout tactics, but differ on how tightly to constrain the execution window."
    else:
        summary = "Approved scalping sources disagree on whether the best edge comes from fading exhaustion or following short-term momentum."
    return [ContradictionRecord(family=family, summary=summary, source_ids=[entry.source_id for entry in entries])]


def _write_quality_side_artifacts(catalog: CorpusCatalog, settings: Settings) -> None:
    for entry in catalog.entries:
        write_json(
            settings.paths().corpus_quality_dir / f"{entry.source_id}.json",
            entry.quality_report.model_dump(mode="json"),
        )
        note = _build_knowledge_note(
            entry,
            "scalping"
            if _family_relevance(entry, "scalping") >= _family_relevance(entry, "day_trading")
            else "day_trading",
        )
        write_json(settings.paths().corpus_notes_dir / f"{entry.source_id}.json", note.model_dump(mode="json"))
        claims = _build_strategy_claims([entry], note.family_relevance_tags[0])
        write_json(
            settings.paths().corpus_claims_dir / f"{entry.source_id}.json",
            [claim.model_dump(mode="json") for claim in claims],
        )


def _catalog_source_files(mirror: Path, settings: Settings, read_policy: ReadPolicy) -> list[Path]:
    paths: list[Path] = [path for path in mirror.rglob("*") if path.is_file()]
    for configured_path in settings.data.supplemental_source_paths:
        source_path = Path(configured_path)
        if not source_path.exists():
            continue
        read_policy.assert_allowed(source_path)
        if source_path not in paths:
            paths.append(source_path)
    return sorted(paths, key=lambda path: str(path).lower())


def _load_metadata(mirror: Path, read_policy: ReadPolicy) -> dict[str, dict]:
    metadata: dict[str, dict] = {}

    json_path = mirror / "_info.json"
    if json_path.exists():
        raw = read_json(read_policy.assert_allowed(json_path))
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    title = str(item.get("title", "")).strip().lower()
                    if title:
                        metadata[title] = item

    info_text_path = mirror / "_info.text"
    if info_text_path.exists():
        for line in read_policy.read_text(info_text_path).splitlines():
            parsed = _parse_metadata_line(line)
            if not parsed:
                continue
            title, note = parsed
            entry = metadata.setdefault(title, {})
            entry["info_text_note"] = note

    trading_path = mirror / "Trading.txt"
    if trading_path.exists():
        for line in read_policy.read_text(trading_path).splitlines():
            title = line.strip().lower()
            if not title:
                continue
            entry = metadata.setdefault(title, {})
            entry["listed_in_trading_txt"] = True

    return metadata


def _parse_metadata_line(line: str) -> tuple[str, str] | None:
    cleaned = line.strip()
    if not cleaned:
        return None
    for separator in (" - ", ": "):
        if separator in cleaned:
            title, note = cleaned.split(separator, 1)
            title = title.strip().lower()
            note = note.strip()
            if title and note:
                return title, note
    return None


def _collect_flagged_chunks(text: str, patterns: list[str], limit: int = 3) -> list[str]:
    signals: list[str] = []
    for chunk in _segment_text(text):
        lowered = chunk.lower()
        if any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in patterns):
            signals.append(_clean_preview(chunk))
        if len(signals) >= limit:
            break
    return signals


def _best_excerpt(title: str, text: str, family: str) -> str:
    chunks = _segment_text(text)
    if not chunks:
        return title
    ranked = sorted(chunks, key=lambda chunk: _excerpt_score(chunk, family), reverse=True)
    for chunk in ranked:
        if _excerpt_score(chunk, family) > 0:
            return _clean_preview(chunk)
    for chunk in ranked:
        if not _looks_like_copyright_or_front_matter(chunk):
            return _clean_preview(chunk)
    return _clean_preview(ranked[0]) if ranked else title


def _best_overall_excerpt(title: str, text: str) -> str:
    scalping_excerpt = _best_excerpt(title, text, "scalping")
    day_excerpt = _best_excerpt(title, text, "day_trading")
    if _excerpt_score(day_excerpt, "day_trading") > _excerpt_score(scalping_excerpt, "scalping"):
        return day_excerpt
    return scalping_excerpt


def _segment_text(text: str, min_chunk_size: int = 220, max_chunk_size: int = 900) -> list[str]:
    cleaned = text.replace("\r", "\n")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    raw_blocks = [block.strip() for block in re.split(r"\n\s*\n+", cleaned) if block.strip()]
    if len(raw_blocks) <= 2:
        raw_blocks = [line.strip() for line in cleaned.splitlines() if line.strip()]
    chunks: list[str] = []
    for block in raw_blocks:
        block = block.strip()
        if not block:
            continue
        if len(block) <= max_chunk_size:
            chunks.append(_clean_preview(block, limit=max_chunk_size))
            continue
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", block)
        buffer: list[str] = []
        current_len = 0
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if current_len + len(sentence) > max_chunk_size and buffer:
                chunks.append(_clean_preview(" ".join(buffer), limit=max_chunk_size))
                buffer = []
                current_len = 0
            buffer.append(sentence)
            current_len += len(sentence)
            if current_len >= min_chunk_size:
                chunks.append(_clean_preview(" ".join(buffer), limit=max_chunk_size))
                buffer = []
                current_len = 0
        if buffer:
            chunks.append(_clean_preview(" ".join(buffer), limit=max_chunk_size))
    return [chunk for chunk in chunks if chunk.strip()]


def _excerpt_score(chunk: str, family: str) -> float:
    if not chunk:
        return -1.0
    lowered = chunk.lower()
    score = 0.0
    for keyword, weight in GENERAL_CONTENT_KEYWORDS.items():
        if keyword in lowered:
            score += weight
    for keyword, weight in FAMILY_KEYWORDS.get(family, {}).items():
        if keyword in lowered:
            score += weight
    if _looks_like_copyright_or_front_matter(chunk):
        score -= 1.5
    if len(chunk) < 100:
        score -= 0.2
    return score


def _looks_like_copyright_or_front_matter(chunk: str) -> bool:
    lowered = chunk.lower()
    if any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in COPYRIGHT_PATTERNS):
        return True
    if any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in FRONT_MATTER_PATTERNS):
        return True
    return False


def _clean_preview(text: str, limit: int = 280) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned[:limit]


def _infer_claim_style(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("breakout", "momentum", "continuation", "trend")):
        return "breakout"
    if any(token in lowered for token in ("fade", "mean reversion", "pullback", "exhaustion")):
        return "fade"
    return "neutral"


def _entry_best_excerpt(entry: CorpusCatalogEntry, family: str) -> str:
    if entry.extracted_text_path and entry.extracted_text_path.exists():
        return _best_excerpt(entry.title, entry.extracted_text_path.read_text(encoding="utf-8"), family)
    return entry.quality_report.best_excerpt or entry.title


def _entry_text(entry: CorpusCatalogEntry) -> str:
    if entry.extracted_text_path and entry.extracted_text_path.exists():
        return entry.extracted_text_path.read_text(encoding="utf-8")
    return entry.quality_report.best_excerpt or entry.title


def _is_book_prior_entry(entry: CorpusCatalogEntry) -> bool:
    title = entry.title.lower()
    return "algorithmic trading" in title or "winning strategies and their rationale" in title


def _extract_typed_claims(entry: CorpusCatalogEntry, family: str, text: str) -> list[StrategyClaim]:
    lowered = text.lower()
    claims: list[StrategyClaim] = []
    confidence = entry.quality_report.relevance_score
    family_tags = [family]

    def add_claim(
        *,
        claim: str,
        claim_type: str,
        prior_effect: str,
        concept_tags: list[str],
    ) -> None:
        claims.append(
            StrategyClaim(
                source_id=entry.source_id,
                family=family,
                claim=claim,
                confidence=confidence,
                claim_type=claim_type,
                prior_effect=prior_effect,
                concept_tags=concept_tags,
                family_relevance_tags=family_tags,
            )
        )

    if any(
        token in lowered
        for token in ("london session", "london open", "opening gap", "opening impulse", "opening range")
    ):
        add_claim(
            claim="Prefer explicit Europe/London-open session anchors instead of broad unanchored intraday persistence.",
            claim_type="session_anchor",
            prior_effect="support",
            concept_tags=["europe-open", "session-anchor", "momentum"],
        )
    if any(
        token in lowered
        for token in ("short holding", "short horizon", "time-based exit", "time based exit", "time exit")
    ):
        add_claim(
            claim="Momentum families should use short holding horizons and explicit time exits.",
            claim_type="holding_horizon",
            prior_effect="support",
            concept_tags=["short-horizon", "time-exit"],
        )
    if "overnight" in lowered and any(
        token in lowered for token in ("no overnight", "without overnight", "avoid overnight", "flat by end of day")
    ):
        add_claim(
            claim="Do not carry these intraday momentum families overnight; same-day flat is preferred.",
            claim_type="overnight_rule",
            prior_effect="veto",
            concept_tags=["overnight", "same-day-flat"],
        )
    if any(
        token in lowered
        for token in ("markets adapt", "horizons compress", "momentum horizons compress", "edge decays")
    ):
        add_claim(
            claim="Momentum drift decays quickly, so late-morning persistence should be penalized unless density support is explicit.",
            claim_type="momentum_event_decay",
            prior_effect="penalty",
            concept_tags=["decay", "adaptation", "late-morning"],
        )
    if any(
        token in lowered
        for token in ("spread", "risk day", "risk filter", "realized volatility", "blackout", "news blackout")
    ):
        add_claim(
            claim="Discovery should use spread, realized-volatility, and calendar-risk filters as a veto layer on fragile momentum setups.",
            claim_type="risk_day_filter",
            prior_effect="support",
            concept_tags=["risk-filter", "spread", "volatility", "calendar"],
        )
    if any(
        token in lowered
        for token in (
            "no significant macro-news momentum in eurusd",
            "no significant macro news momentum in eurusd",
            "eurusd",
        )
    ) and any(token in lowered for token in ("macro-news momentum", "macro news momentum", "release persistence")):
        add_claim(
            claim="Avoid treating EUR/USD macro-news release persistence as a primary momentum family.",
            claim_type="anti_pattern",
            prior_effect="veto",
            concept_tags=["eurusd", "release-persistence", "anti-pattern"],
        )
    if not claims and _is_book_prior_entry(entry):
        add_claim(
            claim="Use the book as a structured prior for Europe-open, short-horizon intraday momentum families.",
            claim_type="generic",
            prior_effect="support",
            concept_tags=["book-prior", "intraday"],
        )
    return claims
