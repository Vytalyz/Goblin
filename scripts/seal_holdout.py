"""Phase 1.6.4 — Seal an OOS holdout slice (encrypted at rest).

Carves the chronologically-latest portion of the research parquet,
encrypts it with Fernet (AES-128-CBC + HMAC-SHA256), writes the
ciphertext into the repo, and stores the key OUTSIDE the repo
(``~/.goblin/holdout_keys/<holdout_id>.key`` by default).

Both the plaintext SHA and ciphertext SHA are written into a manifest
that the Decision Log pins. This is the minimal viable substitute for
a full GPG flow on this Windows host.

D12 reminder: the holdout may be opened exactly twice: once at Phase
2.0 re-gate, once at Phase 2.10 final. Decryption SHOULD be done via
``.github/workflows/holdout-access.yml`` once Phase 1.7 lands it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from cryptography.fernet import Fernet

REPO_ROOT = Path(__file__).resolve().parents[1]


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def bytes_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description="Seal an OOS holdout slice (Phase 1.6.4 / D12).")
    ap.add_argument("--source", default="data/normalized/research/eur_usd_m1.parquet")
    ap.add_argument(
        "--holdout-fraction",
        type=float,
        default=0.20,
        help="Chronologically-latest fraction to seal (0.15-0.20 per plan).",
    )
    ap.add_argument(
        "--ciphertext-out",
        default="Goblin/holdout/ml_p2_holdout.parquet.enc",
        help="Where to write the encrypted holdout (relative to repo root).",
    )
    ap.add_argument("--manifest-out", default="Goblin/holdout/ml_p2_holdout_manifest.json")
    ap.add_argument("--holdout-id", default="HOLDOUT-ML-P2-20260420")
    ap.add_argument(
        "--key-dir",
        default=str(Path.home() / ".goblin" / "holdout_keys"),
        help="Directory OUTSIDE the repo where the key is stored.",
    )
    args = ap.parse_args()

    src = (REPO_ROOT / args.source).resolve()
    if not src.exists():
        print(f"[seal] source not found: {src}", file=sys.stderr)
        return 2
    if not (0.05 <= args.holdout_fraction <= 0.30):
        print(f"[seal] holdout-fraction must be in [0.05, 0.30], got {args.holdout_fraction}", file=sys.stderr)
        return 2

    src_sha = file_sha256(src)
    df = pd.read_parquet(src)
    n = len(df)
    n_holdout = int(round(n * args.holdout_fraction))
    first_idx = n - n_holdout
    last_idx = n - 1
    holdout = df.iloc[first_idx:].reset_index(drop=True)

    # Serialize holdout to a temp parquet bytes blob (in-memory), then encrypt.
    import io

    buf = io.BytesIO()
    holdout.to_parquet(buf, index=False)
    plaintext = buf.getvalue()
    plaintext_sha = bytes_sha256(plaintext)

    # Key storage OUTSIDE repo.
    key_dir = Path(args.key_dir).expanduser()
    key_dir.mkdir(parents=True, exist_ok=True)
    key_path = key_dir / f"{args.holdout_id}.key"
    if key_path.exists():
        print(
            f"[seal] key already exists at {key_path} — refusing to overwrite "
            f"(would orphan the existing ciphertext). Move it aside first.",
            file=sys.stderr,
        )
        return 3
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass  # best-effort on Windows

    cipher = Fernet(key).encrypt(plaintext)
    cipher_sha = bytes_sha256(cipher)
    cipher_out = (REPO_ROOT / args.ciphertext_out).resolve()
    cipher_out.parent.mkdir(parents=True, exist_ok=True)
    cipher_out.write_bytes(cipher)

    manifest = {
        "holdout_id": args.holdout_id,
        "created_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source_dataset_path": str(args.source),
        "source_dataset_sha256": src_sha,
        "holdout_n_rows": int(n_holdout),
        "holdout_first_index": int(first_idx),
        "holdout_last_index": int(last_idx),
        "plaintext_sha256": plaintext_sha,
        "ciphertext_path": str(args.ciphertext_out),
        "ciphertext_sha256": cipher_sha,
        "key_storage_location": str(key_path),
        "encryption_algorithm": "Fernet (AES-128-CBC + HMAC-SHA256)",
    }
    manifest_out = (REPO_ROOT / args.manifest_out).resolve()
    manifest_out.parent.mkdir(parents=True, exist_ok=True)
    manifest_out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"[seal] wrote ciphertext  {cipher_out}  ({len(cipher)} bytes)")
    print(f"[seal] wrote manifest    {manifest_out}")
    print(f"[seal] key (OUT-of-repo) {key_path}")
    print(
        f"[seal] holdout rows={n_holdout}  source_sha={src_sha[:16]}...  "
        f"plaintext_sha={plaintext_sha[:16]}...  cipher_sha={cipher_sha[:16]}..."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
