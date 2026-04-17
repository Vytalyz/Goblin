"""One-time (and reusable pre-push) path sanitization for public GitHub publish.

Replaces absolute local paths with project-relative or placeholder paths
in all tracked artifact files. Does NOT touch:
  - .git/
  - data/state/
  - .venv/
  - .codex/
  - Binary files

The script auto-detects the project root and user home from the current
environment, so it works without hardcoded paths.

Usage:
    python scripts/sanitize_paths_for_publish.py [--dry-run]
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
USER_HOME = Path.home()

# Directories to skip entirely (includes gitignored dirs that don't need sanitization)
SKIP_DIRS = {
    ".git", "data", ".venv", ".codex", "__pycache__", ".pytest_cache",
    "traces", "reports", "published", "dist", "build",
}

# Only process these file extensions
TARGET_EXTENSIONS = {".json", ".md", ".jsonl", ".log", ".ini", ".py", ".txt", ".csv"}


def _build_replacements() -> list[tuple[str, str]]:
    """Build replacement pairs from the current environment.

    Uses the actual repo root and user home paths detected at runtime,
    so no hardcoded paths are needed in source.
    """
    repo_str = str(REPO_ROOT)
    repo_fwd = repo_str.replace("\\", "/")
    home_str = str(USER_HOME)
    home_fwd = home_str.replace("\\", "/")

    # MetaQuotes paths (under user AppData)
    mq_base = str(USER_HOME / "AppData" / "Roaming" / "MetaQuotes")
    mq_base_fwd = mq_base.replace("\\", "/")
    mq_common = mq_base + "\\Terminal\\Common\\Files"
    mq_common_fwd = mq_common.replace("\\", "/")

    # Order: most specific first
    pairs: list[tuple[str, str]] = []

    # Project root with trailing separator -> empty (makes relative)
    pairs.append((repo_str + "\\", ""))
    pairs.append((repo_fwd + "/", ""))

    # Project root bare -> "."
    pairs.append((repo_str, "."))
    pairs.append((repo_fwd, "."))

    # MetaQuotes common files with trailing separator
    pairs.append((mq_common + "\\", "<MT5_COMMON_FILES>/"))
    pairs.append((mq_common_fwd + "/", "<MT5_COMMON_FILES>/"))

    # MetaQuotes root with trailing separator
    pairs.append((mq_base + "\\", "<MT5_APPDATA>/"))
    pairs.append((mq_base_fwd + "/", "<MT5_APPDATA>/"))

    # User home with trailing separator
    pairs.append((home_str + "\\", "<USER_HOME>/"))
    pairs.append((home_fwd + "/", "<USER_HOME>/"))

    # User home bare
    pairs.append((home_str, "<USER_HOME>"))
    pairs.append((home_fwd, "<USER_HOME>"))

    # Also add lowercase variants for case-insensitive matches (e.g. git normalizes case)
    for old, new in list(pairs):
        lowered = old.lower()
        if lowered != old and (lowered, new) not in pairs:
            pairs.append((lowered, new))

    return pairs


def _build_json_replacements() -> list[tuple[str, str]]:
    """Build double-escaped replacements for JSON string content."""
    repo_esc = str(REPO_ROOT).replace("\\", "\\\\")
    home_esc = str(USER_HOME).replace("\\", "\\\\")
    mq_base_esc = str(USER_HOME / "AppData" / "Roaming" / "MetaQuotes").replace("\\", "\\\\")
    mq_common_esc = mq_base_esc + "\\\\Terminal\\\\Common\\\\Files"

    pairs: list[tuple[str, str]] = []

    # Project root with trailing double-escaped separator
    pairs.append((repo_esc + "\\\\", ""))
    # Project root bare
    pairs.append((repo_esc, "."))
    # MetaQuotes common files
    pairs.append((mq_common_esc + "\\\\", "<MT5_COMMON_FILES>/"))
    # MetaQuotes root
    pairs.append((mq_base_esc + "\\\\", "<MT5_APPDATA>/"))
    # User home with trailing
    pairs.append((home_esc + "\\\\", "<USER_HOME>/"))
    # User home bare
    pairs.append((home_esc, "<USER_HOME>"))

    return pairs


REPLACEMENTS = _build_replacements()
JSON_REPLACEMENTS = _build_json_replacements()

# MT5 terminal hashes: 32-char uppercase hex identifying a local install
_TERMINAL_HASH_RE = re.compile(r"(Terminal[/\\\\]+)[A-Fa-f0-9]{32}")


def should_skip(path: Path) -> bool:
    """Return True if this path should be skipped."""
    parts = path.relative_to(REPO_ROOT).parts
    if not parts:
        return True
    return parts[0] in SKIP_DIRS


def sanitize_file(filepath: Path, dry_run: bool = False) -> int:
    """Sanitize a single file. Returns the number of replacements made."""
    try:
        content = filepath.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return 0

    total_replacements = 0

    # Apply JSON double-escaped replacements first (for .json/.jsonl files)
    if filepath.suffix in (".json", ".jsonl"):
        for old, new in JSON_REPLACEMENTS:
            count = content.count(old)
            if count > 0:
                content = content.replace(old, new)
                total_replacements += count

    # Apply standard replacements
    for old, new in REPLACEMENTS:
        count = content.count(old)
        if count > 0:
            content = content.replace(old, new)
            total_replacements += count

    # Replace MT5 terminal hashes (32-char hex after Terminal\ or Terminal/)
    hash_replaced = _TERMINAL_HASH_RE.subn(r"\1<MT5_TERMINAL_HASH>", content)
    if hash_replaced[1] > 0:
        content = hash_replaced[0]
        total_replacements += hash_replaced[1]

    if total_replacements > 0 and not dry_run:
        filepath.write_text(content, encoding="utf-8")

    return total_replacements


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print("=== DRY RUN -- no files will be modified ===\n")

    print(f"Repo root: {REPO_ROOT}")
    print(f"User home: {USER_HOME}")
    print(f"Replacement patterns: {len(REPLACEMENTS)} standard + {len(JSON_REPLACEMENTS)} JSON\n")

    files_changed = 0
    total_replacements = 0
    changed_files: list[tuple[str, int]] = []

    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        current = Path(dirpath)

        # Prune skipped directories
        dirnames[:] = [
            d for d in dirnames
            if not should_skip(current / d)
        ]

        for filename in filenames:
            filepath = current / filename
            if filepath.suffix.lower() not in TARGET_EXTENSIONS:
                continue

            count = sanitize_file(filepath, dry_run=dry_run)
            if count > 0:
                rel = filepath.relative_to(REPO_ROOT)
                changed_files.append((str(rel), count))
                files_changed += 1
                total_replacements += count

    # Summary
    print(f"{'[DRY RUN] ' if dry_run else ''}Sanitization complete.")
    print(f"  Files changed: {files_changed}")
    print(f"  Total replacements: {total_replacements}")

    if changed_files:
        print("\nChanged files:")
        for rel_path, count in sorted(changed_files):
            print(f"  {rel_path}: {count} replacements")

    # Post-check: scan for any remaining user paths
    print("\n=== Post-scan for remaining user paths ===")
    home_str = str(USER_HOME)
    home_fwd = home_str.replace("\\", "/")
    remaining = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        current = Path(dirpath)
        dirnames[:] = [d for d in dirnames if not should_skip(current / d)]
        for filename in filenames:
            filepath = current / filename
            if filepath.suffix.lower() not in TARGET_EXTENSIONS:
                continue
            try:
                text = filepath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for marker in (home_str, home_fwd):
                if marker in text:
                    remaining.append(str(filepath.relative_to(REPO_ROOT)))
                    break

    if remaining:
        print(f"  WARNING: {len(remaining)} files still contain user paths:")
        for r in remaining:
            print(f"    {r}")
    else:
        print("  OK: 0 files contain user paths.")


if __name__ == "__main__":
    main()
