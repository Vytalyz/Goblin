from __future__ import annotations

import os

# --- Ensure .codex directory exists for all test environments (local and CI) ---
import pytest


@pytest.fixture(scope="session", autouse=True)
def setup_codex_directory():
    codex_path = ".codex"
    if not os.path.exists(codex_path):
        os.makedirs(codex_path, exist_ok=True)
    yield


import json
import math
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from ebooklib import epub
from pypdf import PdfWriter

from agentic_forex.config import load_settings
from agentic_forex.goblin.controls import write_strategy_rationale_card
from agentic_forex.utils.paths import ProjectPaths

TEMPLATE_ROOT = Path(__file__).resolve().parents[1]


def scaffold_project(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name in (
        "workflows",
        "prompts",
        "config",
        "agents",
        "skills",
        "knowledge",
        ".codex",
        ".agents",
        "automations",
        "src",
    ):
        template_dir = TEMPLATE_ROOT / name
        if template_dir.is_dir():
            shutil.copytree(template_dir, root / name, dirs_exist_ok=True)
        else:
            (root / name).mkdir(parents=True, exist_ok=True)
    _ensure_codex_scaffolding(root)
    ProjectPaths.from_root(root).ensure_directories()
    return root


def _ensure_codex_scaffolding(root: Path) -> None:
    """Create minimal .codex structure when the template copy is empty (CI)."""
    codex_dir = root / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    config_path = codex_dir / "config.toml"
    if not config_path.exists():
        config_path.write_text(
            'sandbox_mode = "workspace-write"\n\n[features]\ncodex_hooks = false\n',
            encoding="utf-8",
        )
    rules_dir = codex_dir / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    rules_file = rules_dir / "default.rules"
    if not rules_file.exists():
        rules_file.write_text("# Goblin test rules stub\n", encoding="utf-8")
    agents_dir = codex_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    if not any(agents_dir.glob("*.toml")):
        (agents_dir / "portfolio_orchestrator.toml").write_text(
            '# Stub for test scaffolding\nname = "portfolio_orchestrator"\n',
            encoding="utf-8",
        )


def create_corpus_mirror(base_dir: Path) -> Path:
    mirror = base_dir / "gnidart mirror"
    mirror.mkdir(parents=True, exist_ok=True)
    (mirror / "_info.json").write_text(
        json.dumps(
            [
                {
                    "title": "Scalp Intraday Playbook",
                    "author": "Test Author",
                    "rating": 5,
                },
                {
                    "title": "Noisy Archive",
                    "author": "Unknown",
                    "rating": 1,
                },
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    (mirror / "_info.text").write_text(
        "Day Trading Session Guide - Session breakout notes.\n",
        encoding="utf-8",
    )
    (mirror / "Trading.txt").write_text("FX Notes\n", encoding="utf-8")
    (mirror / "Scalp Intraday Playbook.txt").write_text(
        (
            "Copyright 2024 Test Author. All rights reserved. No part of this publication may be reproduced.\n\n"
            "Table of Contents\n1. Setup\n2. Entries\n3. Exits\n\n"
            "Europe-session breakout scalp: trade intraday directional expansion when momentum, session structure, "
            "and price action align. Wait for breakout confirmation, keep spread contained, and use explicit stop, "
            "target, and timeout rules.\n"
        ),
        encoding="utf-8",
    )
    (mirror / "Algorithmic Trading - Winning Strategies and Their Rationale 2013.txt").write_text(
        (
            "Algorithmic Trading - Winning Strategies and Their Rationale 2013\n\n"
            "At the London open, short-horizon momentum can emerge from the opening gap or opening impulse.\n"
            "Momentum horizons compress as markets adapt, so time-based exits matter and late-morning continuation should be treated cautiously.\n"
            "For EURUSD there is no significant macro-news momentum edge worth relying on as a primary family.\n"
            "Do not carry these intraday momentum trades overnight; stay flat by end of day.\n"
            "Risk filters should account for spread shocks, realized-volatility shocks, and calendar blackout conditions.\n"
        ),
        encoding="utf-8",
    )
    (mirror / "Noisy Archive.txt").write_text("miscellaneous unrelated diary text", encoding="utf-8")

    book = epub.EpubBook()
    book.set_identifier("day-guide")
    book.set_title("Day Trading Session Guide")
    book.set_language("en")
    chapter = epub.EpubHtml(title="Guide", file_name="guide.xhtml", lang="en")
    chapter.content = (
        "<h1>Day Trading Session Guide</h1><p>Focus on session range breaks and clean intraday structure.</p>"
    )
    book.add_item(chapter)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.toc = (chapter,)
    book.spine = ["nav", chapter]
    epub.write_epub(str(mirror / "Day Trading Session Guide.epub"), book)

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with (mirror / "FX Notes.pdf").open("wb") as handle:
        writer.write(handle)

    (mirror / "ignore.me").write_text("ignored", encoding="utf-8")
    return mirror


def create_book_prior_file(base_dir: Path) -> Path:
    path = base_dir / "Algorithmic Trading - Winning Strategies and Their Rationale 2013.txt"
    path.write_text(
        (
            "Algorithmic Trading - Winning Strategies and Their Rationale 2013\n\n"
            "London open momentum is better treated as an opening-gap or opening-impulse effect than as broad all-morning persistence.\n"
            "Momentum horizons compress as markets adapt, so short holding horizons and explicit time exits are preferred.\n"
            "No overnight carry should be assumed for this intraday momentum style.\n"
            "There is no significant EURUSD macro-news momentum edge worth using as a release-persistence default.\n"
            "Risk day filters should watch spread shock, realized-volatility shock, and calendar blackout severity.\n"
        ),
        encoding="utf-8",
    )
    return path


def create_market_csv(base_dir: Path, rows: int = 720) -> Path:
    output = base_dir / "eurusd_m1.csv"
    start = datetime(2024, 1, 1, tzinfo=UTC)
    records: list[dict] = []
    previous_mid = 1.1000
    for index in range(rows):
        timestamp = start + timedelta(minutes=index)
        mid_close = 1.1000 + 0.0009 * math.sin(index / 8) + 0.0005 * math.sin(index / 31)
        mid_open = previous_mid
        range_width = 0.00014 + 0.00003 * ((index % 9) / 9)
        mid_high = max(mid_open, mid_close) + range_width / 2
        mid_low = min(mid_open, mid_close) - range_width / 2
        spread = 0.00008 + 0.00001 * (index % 4)
        records.append(
            {
                "timestamp_utc": timestamp.isoformat().replace("+00:00", "Z"),
                "bid_o": round(mid_open - spread / 2, 6),
                "bid_h": round(mid_high - spread / 2, 6),
                "bid_l": round(mid_low - spread / 2, 6),
                "bid_c": round(mid_close - spread / 2, 6),
                "ask_o": round(mid_open + spread / 2, 6),
                "ask_h": round(mid_high + spread / 2, 6),
                "ask_l": round(mid_low + spread / 2, 6),
                "ask_c": round(mid_close + spread / 2, 6),
                "volume": 100 + (index % 17),
            }
        )
        previous_mid = mid_close
    pd.DataFrame.from_records(records).to_csv(output, index=False)
    return output


def create_oanda_candles_json(base_dir: Path, rows: int = 360) -> Path:
    output = base_dir / "eurusd_oanda.json"
    start = datetime(2024, 1, 1, tzinfo=UTC)
    candles: list[dict] = []
    previous_mid = 1.1000
    for index in range(rows):
        timestamp = start + timedelta(minutes=index)
        mid_close = 1.1000 + 0.0008 * math.sin(index / 9) + 0.0004 * math.cos(index / 23)
        mid_open = previous_mid
        spread = 0.00009 + 0.00001 * (index % 3)
        bid_o = mid_open - spread / 2
        ask_o = mid_open + spread / 2
        bid_c = mid_close - spread / 2
        ask_c = mid_close + spread / 2
        bid_h = max(bid_o, bid_c) + 0.00006
        bid_l = min(bid_o, bid_c) - 0.00006
        ask_h = bid_h + spread
        ask_l = bid_l + spread
        candles.append(
            {
                "complete": True,
                "time": timestamp.isoformat().replace("+00:00", "Z"),
                "volume": 100 + (index % 11),
                "bid": {
                    "o": f"{bid_o:.5f}",
                    "h": f"{bid_h:.5f}",
                    "l": f"{bid_l:.5f}",
                    "c": f"{bid_c:.5f}",
                },
                "ask": {
                    "o": f"{ask_o:.5f}",
                    "h": f"{ask_h:.5f}",
                    "l": f"{ask_l:.5f}",
                    "c": f"{ask_c:.5f}",
                },
            }
        )
        previous_mid = mid_close
    output.write_text(
        json.dumps(
            {
                "instrument": "EUR_USD",
                "granularity": "M1",
                "candles": candles,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return output


def create_economic_calendar_csv(base_dir: Path) -> Path:
    output = base_dir / "economic_calendar.csv"
    records = [
        {
            "timestamp_utc": "2024-01-01T07:30:00Z",
            "currency": "EUR",
            "impact": "high",
            "title": "Eurozone CPI",
        },
        {
            "timestamp_utc": "2024-01-01T09:00:00Z",
            "currency": "USD",
            "impact": "high",
            "title": "US ISM Manufacturing",
        },
        {
            "timestamp_utc": "2024-01-01T12:00:00Z",
            "currency": "JPY",
            "impact": "medium",
            "title": "Japan Consumer Confidence",
        },
    ]
    pd.DataFrame.from_records(records).to_csv(output, index=False)
    return output


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    return scaffold_project(tmp_path / "Agentic Forex Temp")


@pytest.fixture
def settings(project_root: Path):
    resolved = load_settings(project_root=project_root)
    write_strategy_rationale_card(
        resolved,
        family="scalping",
        thesis="Scalping family remains governed by deterministic invalidation, regime, and execution assumptions before any live/demo progression.",
        invalidation_conditions=["out-of-sample metrics fail policy floors"],
        hostile_regimes=["spread and slippage shock windows"],
        execution_assumptions=["bounded spread and deterministic fill-delay envelope"],
        non_deployable_conditions=["walk-forward instability or unresolved governance incidents"],
    )
    write_strategy_rationale_card(
        resolved,
        family="day_trading",
        thesis="Day-trading family remains governed by session-anchored rationale and strict comparison integrity controls.",
        invalidation_conditions=["edge concentration disappears in unseen windows"],
        hostile_regimes=["macro-event volatility dislocations"],
        execution_assumptions=["session window and risk envelope remain stable"],
        non_deployable_conditions=["comparison integrity constraints are violated"],
    )
    write_strategy_rationale_card(
        resolved,
        family="throughput_research",
        thesis="Throughput research remains bounded by family-level rationale, invalidation controls, and strict experiment-accounting discipline.",
        invalidation_conditions=["bounded diagnosis fails to produce robust refinements"],
        hostile_regimes=["churning low-signal windows that encourage over-search"],
        execution_assumptions=["controlled mutation scope with deterministic lineage"],
        non_deployable_conditions=["family enters suspended experiment-accounting state"],
    )
    write_strategy_rationale_card(
        resolved,
        family="impulse_transition_research",
        thesis="Impulse-transition research remains valid only when first-window failures are diagnosable with repeatable regime-conditioned corrections.",
        invalidation_conditions=["post-correction diagnostics remain ambiguous across iterations"],
        hostile_regimes=["persistent phase drift across walk-forward windows"],
        execution_assumptions=["session and context slices remain measurable and comparable"],
        non_deployable_conditions=["comparison integrity or methodology rubric controls fail"],
    )
    resolved.data.supplemental_source_paths = []
    return resolved
