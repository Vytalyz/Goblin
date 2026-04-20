"""Dataset SHA-256 pin verifier (ML-1.7).

Verifies that the canonical research dataset
``data/normalized/research/eur_usd_m1.parquet`` has the expected SHA-256
that was pinned at the start of the ML phase work. Used by the
``dataset-sha-pin-check`` CI job.

Usage:
    python tools/verify_dataset_sha.py [--path PATH] [--expected SHA]
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = REPO_ROOT / "data" / "normalized" / "research" / "eur_usd_m1.parquet"
PINNED_SHA256 = "7875ba5af620476aaba80cdec0c86680b343f70a02bf19eb40695517378ed8f1"


def compute_sha256(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def verify(path: Path, expected: str) -> str:
    actual = compute_sha256(path)
    if actual.lower() != expected.lower():
        raise ValueError(f"dataset SHA mismatch for {path}\n  expected: {expected}\n    actual: {actual}")
    return actual


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--expected", default=PINNED_SHA256)
    args = parser.parse_args(argv)
    if not args.path.exists():
        print(f"[verify_dataset_sha] dataset not found: {args.path}", file=sys.stderr)
        return 2
    try:
        sha = verify(args.path, args.expected)
    except ValueError as exc:
        print(f"[verify_dataset_sha] FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"[verify_dataset_sha] OK: {args.path.name} sha256={sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
