from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


PROJECT_MARKERS = (
    "pyproject.toml",
    "AGENTS.md",
    "README.md",
    "STATUS.md",
    "PLAN.md",
)

CACHE_OR_UTILITY_NAMES = {
    ".codex-tmp",
    ".npm-cache",
    ".venv",
    "tmp",
    ".git",
}


def normalize_path(path: Path | str | None) -> str | None:
    if path is None:
        return None
    return Path(path).resolve().as_posix().rstrip("/").lower()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit top-level Playground folders for standalone git-repo readiness."
    )
    parser.add_argument(
        "root",
        type=Path,
        help="Container directory whose immediate child folders should be audited.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for a JSON report.",
    )
    return parser.parse_args()


def detect_git_root(path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def has_project_markers(path: Path) -> dict[str, bool]:
    return {marker: (path / marker).exists() for marker in PROJECT_MARKERS}


def classify_entry(root: Path, entry: Path) -> tuple[str, list[str], str | None]:
    markers = has_project_markers(entry)
    git_path = entry / ".git"
    local_git = git_path.exists()
    effective_git_root = normalize_path(detect_git_root(entry))
    entry_path = normalize_path(entry)
    root_path = normalize_path(root)
    notes: list[str] = []

    if entry.name in CACHE_OR_UTILITY_NAMES:
        return "utility-or-cache", notes, effective_git_root

    if git_path.is_dir() and effective_git_root == entry_path:
        return "standalone-repo", notes, effective_git_root

    if git_path.is_file() and effective_git_root == entry_path:
        return "git-worktree", notes, effective_git_root

    if local_git and effective_git_root and effective_git_root != entry_path:
        notes.append("local .git exists but resolves to another git root")
        return "linked-repo-or-worktree", notes, effective_git_root

    if any(markers.values()):
        if effective_git_root == root_path:
            notes.append("project markers found but git resolves to shared container root")
        return "project-needs-local-repo", notes, effective_git_root

    if effective_git_root == root_path:
        notes.append("non-project folder still resolves to shared container root")
        return "nested-under-shared-root", notes, effective_git_root

    return "content-or-utility", notes, effective_git_root


def build_report(root: Path) -> dict:
    root = root.resolve()
    entries: list[dict] = []
    anomalies: list[dict] = []
    shared_root = normalize_path(detect_git_root(root))

    for entry in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not entry.is_dir():
            continue

        markers = has_project_markers(entry)
        classification, notes, effective_git_root = classify_entry(root, entry)
        item = {
            "name": entry.name,
            "path": str(entry),
            "classification": classification,
            "has_local_git": (entry / ".git").exists(),
            "effective_git_root": effective_git_root,
            "markers": markers,
            "notes": notes,
        }
        entries.append(item)

        if classification == "project-needs-local-repo":
            anomalies.append(
                {
                    "type": "missing_local_repo",
                    "folder": entry.name,
                    "detail": "Project markers exist, but the folder does not have its own git root.",
                }
            )
        if classification == "git-worktree":
            anomalies.append(
                {
                    "type": "git_worktree",
                    "folder": entry.name,
                    "detail": "Folder is a git worktree and should be managed through its owning repository.",
                }
            )
        if classification == "linked-repo-or-worktree":
            anomalies.append(
                {
                    "type": "linked_repo_or_worktree",
                    "folder": entry.name,
                    "detail": "Folder has .git metadata, but its effective root resolves elsewhere.",
                }
            )
        if any(markers.values()) and effective_git_root == shared_root and normalize_path(entry) != shared_root:
            anomalies.append(
                {
                    "type": "shared_root_bleed",
                    "folder": entry.name,
                    "detail": "Project-like folder resolves to the container git root instead of its own root.",
                }
            )

    return {
        "audit_root": str(root),
        "container_git_root": shared_root,
        "entry_count": len(entries),
        "entries": entries,
        "anomalies": anomalies,
    }


def main() -> int:
    args = parse_args()
    report = build_report(args.root)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())