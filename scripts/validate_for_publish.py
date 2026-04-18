"""Pre-publish validation gate for the Goblin repository.

Runs the same checks a QA engineer, senior engineer, and security engineer
would perform before any code is pushed to a public GitHub repository:

  1. Secret scan       — no API keys, tokens, or passwords in tracked files
  2. Path scan         — no absolute user-specific paths in tracked files
  3. Binary scan       — no compiled binaries in tracked files
  4. Sensitive dirs    — data/state/, .codex/, .env tracked = fail
  5. Config hygiene    — local.toml must not be tracked
  6. Artifact sanitize — run sanitize_paths_for_publish in dry-run mode
  7. Test suite        — pytest must pass (optional, skippable)

Usage:
  python scripts/validate_for_publish.py            # full validation
  python scripts/validate_for_publish.py --skip-tests  # skip pytest
  python scripts/validate_for_publish.py --fix      # auto-fix where possible
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# ── Patterns that must never appear in tracked files ────────────────────

SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"""(OANDA_API_TOKEN|OPENAI_API_KEY)\s*[:=]\s*['"][a-zA-Z0-9]"""),
    re.compile(r"""sk-[a-zA-Z0-9]{20,}"""),
    re.compile(r"""Bearer\s+[a-zA-Z0-9\-_]{20,}"""),
    re.compile(r"""(api[_-]?key|api[_-]?token|secret|password)\s*[:=]\s*['"][^'"]{8,}""", re.IGNORECASE),
]

PATH_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"""C:\\Users\\[^\\]+\\""", re.IGNORECASE),
    re.compile(r"""C:/Users/[^/]+/""", re.IGNORECASE),
]

# MT5 terminal hashes are 32-char hex strings that identify a local install
TERMINAL_HASH_PATTERN = re.compile(r"Terminal[/\\][A-Fa-f0-9]{32}")

BINARY_EXTENSIONS = {".exe", ".ex5", ".dll", ".duckdb", ".parquet", ".so", ".dylib"}
FORBIDDEN_TRACKED_EXTENSIONS = {".log"}

# Extensions worth scanning for secrets and paths (skip large data files)
TEXT_SCAN_EXTENSIONS = {
    ".py",
    ".md",
    ".toml",
    ".yml",
    ".yaml",
    ".json",
    ".jsonl",
    ".txt",
    ".csv",
    ".ini",
    ".cfg",
    ".conf",
    ".env",
    ".sh",
    ".ps1",
    ".bat",
    ".cmd",
    ".mq5",
    ".mqh",
    ".html",
}

# Directories to skip during content scanning (large artifact dirs)
SKIP_SCAN_DIRS = {
    "data",
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
    "experiments",
    "approvals",
    "published",
    "reports",
    "traces",
}

FORBIDDEN_TRACKED_PREFIXES = ["data/state/", ".codex/"]
FORBIDDEN_TRACKED_FILES = [".env", "config/local.toml"]

# Files that are expected to contain path-like patterns for documentation
ALLOWLISTED_FILES = {
    ".env.example",
    "config/local.toml.example",
    "scripts/sanitize_paths_for_publish.py",
    "scripts/validate_for_publish.py",
    ".github/copilot-instructions.md",
}


def _git_tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [f for f in result.stdout.strip().splitlines() if f]


def _scannable_files(tracked_files: list[str]) -> list[str]:
    """Filter to files worth scanning for content (skip large data, binaries)."""
    out: list[str] = []
    for rel_path in tracked_files:
        parts = rel_path.replace("\\", "/").split("/")
        if parts[0] in SKIP_SCAN_DIRS:
            continue
        suffix = Path(rel_path).suffix.lower()
        if suffix in TEXT_SCAN_EXTENSIONS or suffix == "":
            out.append(rel_path)
    return out


def _read_safe(filepath: Path) -> str | None:
    try:
        return filepath.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return None


class Finding:
    def __init__(self, category: str, severity: str, file: str, line: int | None, message: str):
        self.category = category
        self.severity = severity
        self.file = file
        self.line = line
        self.message = message

    def __str__(self) -> str:
        loc = f"{self.file}:{self.line}" if self.line else self.file
        return f"[{self.severity}] {self.category}: {loc} — {self.message}"


def _scan_content(tracked_files: list[str]) -> tuple[list[Finding], list[Finding]]:
    """Single-pass content scan for both secrets and paths."""
    secret_findings: list[Finding] = []
    path_findings: list[Finding] = []
    scannable = _scannable_files(tracked_files)
    total = len(scannable)
    for idx, rel_path in enumerate(scannable, 1):
        if idx % 200 == 0:
            print(f"  … scanned {idx}/{total} files", flush=True)
        if rel_path in ALLOWLISTED_FILES:
            continue
        filepath = REPO_ROOT / rel_path
        content = _read_safe(filepath)
        if content is None:
            continue
        for line_num, line in enumerate(content.splitlines(), 1):
            for pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    safe_line = line.strip()[:120]
                    secret_findings.append(
                        Finding("SECRET", "CRITICAL", rel_path, line_num, f"Potential secret: {safe_line}…")
                    )
            for pattern in PATH_PATTERNS:
                if pattern.search(line):
                    path_findings.append(
                        Finding("PATH", "HIGH", rel_path, line_num, f"Absolute user path found: {line.strip()[:120]}")
                    )
    print(f"  … scanned {total}/{total} files", flush=True)
    return secret_findings, path_findings


def scan_binaries(tracked_files: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for rel_path in tracked_files:
        suffix = Path(rel_path).suffix.lower()
        if suffix in BINARY_EXTENSIONS:
            findings.append(Finding("BINARY", "HIGH", rel_path, None, f"Binary file tracked: {suffix}"))
        if suffix in FORBIDDEN_TRACKED_EXTENSIONS:
            findings.append(Finding("LOG_FILE", "HIGH", rel_path, None, f"Log/temp file tracked: {suffix}"))
    return findings


def scan_terminal_hashes(tracked_files: list[str]) -> list[Finding]:
    """Detect MT5 terminal hashes that identify a local install."""
    findings: list[Finding] = []
    for rel_path in tracked_files:
        filepath = REPO_ROOT / rel_path
        content = _read_safe(filepath)
        if content is None:
            continue
        for line_num, line in enumerate(content.splitlines(), 1):
            if TERMINAL_HASH_PATTERN.search(line):
                findings.append(
                    Finding(
                        "TERMINAL_HASH", "HIGH", rel_path, line_num, "MT5 terminal hash exposes local install identity"
                    )
                )
                break  # one finding per file is enough
    return findings


def scan_repo_completeness() -> list[Finding]:
    """Check that required repo files exist for a public release."""
    findings: list[Finding] = []
    required = {
        "LICENSE": "Missing LICENSE file",
        "SECURITY.md": "Missing SECURITY.md vulnerability-reporting policy",
        "README.md": "Missing README.md",
    }
    for filename, message in required.items():
        if not (REPO_ROOT / filename).exists():
            findings.append(Finding("COMPLETENESS", "HIGH", filename, None, message))
    return findings


def scan_sensitive_dirs(tracked_files: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for rel_path in tracked_files:
        normalized = rel_path.replace("\\", "/")
        for prefix in FORBIDDEN_TRACKED_PREFIXES:
            if normalized.startswith(prefix):
                findings.append(
                    Finding(
                        "SENSITIVE_DIR", "CRITICAL", rel_path, None, f"File in forbidden tracked directory: {prefix}"
                    )
                )
        for forbidden in FORBIDDEN_TRACKED_FILES:
            if normalized == forbidden:
                findings.append(
                    Finding("SENSITIVE_FILE", "CRITICAL", rel_path, None, "Local config file must not be tracked")
                )
    return findings


def scan_config_hygiene() -> list[Finding]:
    findings: list[Finding] = []
    gitignore_path = REPO_ROOT / ".gitignore"
    if not gitignore_path.exists():
        findings.append(Finding("CONFIG", "HIGH", ".gitignore", None, "Missing .gitignore"))
        return findings
    content = gitignore_path.read_text(encoding="utf-8")
    required_patterns = [".env", "config/local.toml", "data/state/", ".codex/", "*.log"]
    for pattern in required_patterns:
        if pattern not in content:
            findings.append(
                Finding("CONFIG", "HIGH", ".gitignore", None, f"Missing required gitignore pattern: {pattern}")
            )
    # Verify .env.example and local.toml.example exist
    if not (REPO_ROOT / ".env.example").exists():
        findings.append(Finding("CONFIG", "MEDIUM", ".env.example", None, "Missing .env.example template"))
    if not (REPO_ROOT / "config" / "local.toml.example").exists():
        findings.append(
            Finding("CONFIG", "MEDIUM", "config/local.toml.example", None, "Missing local.toml.example template")
        )
    return findings


def run_sanitizer_dry_run() -> list[Finding]:
    findings: list[Finding] = []
    sanitizer = REPO_ROOT / "scripts" / "sanitize_paths_for_publish.py"
    if not sanitizer.exists():
        findings.append(
            Finding("SANITIZER", "MEDIUM", "scripts/sanitize_paths_for_publish.py", None, "Sanitizer script not found")
        )
        return findings
    result = subprocess.run(
        [sys.executable, str(sanitizer), "--dry-run"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        findings.append(
            Finding(
                "SANITIZER",
                "HIGH",
                "scripts/sanitize_paths_for_publish.py",
                None,
                f"Sanitizer dry-run failed: {result.stderr.strip()[:200]}",
            )
        )
    # Check output for "files would be changed"
    if "would be changed" in result.stdout and "0 files would be changed" not in result.stdout:
        findings.append(
            Finding("SANITIZER", "HIGH", "artifacts", None, "Sanitizer found unsanitized paths in artifact files")
        )
    return findings


def run_tests() -> list[Finding]:
    findings: list[Finding] = []
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--tb=short", "-q", "-x"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        summary_lines = result.stdout.strip().splitlines()[-5:]
        findings.append(Finding("TESTS", "HIGH", "tests/", None, f"Test suite failed: {' | '.join(summary_lines)}"))
    return findings


def validate(*, skip_tests: bool = False, fix: bool = False) -> list[Finding]:
    tracked = _git_tracked_files()
    all_findings: list[Finding] = []

    print("🔍 [1/9] Scanning source for secrets and absolute paths...", flush=True)
    secret_findings, path_findings = _scan_content(tracked)
    all_findings.extend(secret_findings)
    all_findings.extend(path_findings)

    print("🔍 [2/9] Scanning for tracked binaries and log files...", flush=True)
    all_findings.extend(scan_binaries(tracked))

    print("🔍 [3/9] Scanning artifacts for MT5 terminal hashes...", flush=True)
    # Only scan artifact dirs that commonly contain MT5 paths
    hash_candidates = [f for f in tracked if f.startswith(("approvals/", "experiments/"))]
    all_findings.extend(scan_terminal_hashes(hash_candidates))

    print("🔍 [4/9] Checking sensitive directories...", flush=True)
    all_findings.extend(scan_sensitive_dirs(tracked))

    print("🔍 [5/9] Checking config hygiene...", flush=True)
    all_findings.extend(scan_config_hygiene())

    print("🔍 [6/9] Checking repo completeness (LICENSE, SECURITY, README)...", flush=True)
    all_findings.extend(scan_repo_completeness())

    print("🔍 [7/9] Running sanitizer dry-run...", flush=True)
    all_findings.extend(run_sanitizer_dry_run())

    if not skip_tests:
        print("🔍 [8/9] Running test suite...", flush=True)
        all_findings.extend(run_tests())
    else:
        print("⏩ [8/9] Test suite skipped", flush=True)

    print("🔍 [9/9] Summary...", flush=True)

    if fix and all_findings:
        fixable = [f for f in all_findings if f.category == "SANITIZER" and "unsanitized" in f.message]
        if fixable:
            print("\n🔧 Auto-fixing: running sanitizer...")
            subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" / "sanitize_paths_for_publish.py")],
                cwd=REPO_ROOT,
            )

    return all_findings


def _print_report(findings: list[Finding]) -> None:
    if not findings:
        print("\n✅ PUBLISH VALIDATION PASSED — no findings")
        return

    critical = [f for f in findings if f.severity == "CRITICAL"]
    high = [f for f in findings if f.severity == "HIGH"]
    medium = [f for f in findings if f.severity == "MEDIUM"]

    print(f"\n{'=' * 60}")
    print("PUBLISH VALIDATION REPORT")
    print(f"{'=' * 60}")
    print(f"  CRITICAL: {len(critical)}")
    print(f"  HIGH:     {len(high)}")
    print(f"  MEDIUM:   {len(medium)}")
    print(f"{'=' * 60}")

    for finding in findings:
        print(f"  {finding}")

    if critical or high:
        print(f"\n❌ PUBLISH BLOCKED — resolve {len(critical)} critical and {len(high)} high findings first")
    else:
        print(f"\n⚠️  PUBLISH ALLOWED with {len(medium)} medium findings (review recommended)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-publish validation gate")
    parser.add_argument("--skip-tests", action="store_true", help="Skip pytest run")
    parser.add_argument("--fix", action="store_true", help="Auto-fix sanitizable findings")
    args = parser.parse_args()

    findings = validate(skip_tests=args.skip_tests, fix=args.fix)
    _print_report(findings)

    critical_or_high = [f for f in findings if f.severity in ("CRITICAL", "HIGH")]
    sys.exit(1 if critical_or_high else 0)


if __name__ == "__main__":
    main()
