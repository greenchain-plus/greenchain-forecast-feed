#!/usr/bin/env python3
"""Create the detached RSA/SHA-256 signature consumed by Green CHAIN+."""

from __future__ import annotations

import argparse
import base64
import hashlib
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> subprocess.CompletedProcess[bytes]:
    process = subprocess.run(command, capture_output=True, check=False)
    if process.returncode != 0:
        raise RuntimeError(process.stderr.decode("utf-8", errors="replace").strip())
    return process


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument("--public-key", type=Path, default=ROOT / "keys/forecast_public.pem")
    parser.add_argument("--feed", type=Path, default=ROOT / "public/forecast/latest.json")
    parser.add_argument("--signature", type=Path, default=ROOT / "public/forecast/latest.sig")
    parser.add_argument("--checksum", type=Path, default=ROOT / "public/forecast/latest.sha256")
    parser.add_argument("--marker", type=Path, default=ROOT / "state/signing_required")
    args = parser.parse_args()
    for path in (args.feed, args.private_key, args.public_key):
        if not path.is_file():
            raise FileNotFoundError(path)
    with tempfile.NamedTemporaryFile(suffix=".sig", delete=False) as temporary:
        binary_signature = Path(temporary.name)
    try:
        run(["openssl", "dgst", "-sha256", "-sign", str(args.private_key),
             "-out", str(binary_signature), str(args.feed)])
        run(["openssl", "dgst", "-sha256", "-verify", str(args.public_key),
             "-signature", str(binary_signature), str(args.feed)])
        args.signature.parent.mkdir(parents=True, exist_ok=True)
        args.signature.write_text(
            base64.b64encode(binary_signature.read_bytes()).decode("ascii") + "\n",
            encoding="ascii")
        digest = hashlib.sha256(args.feed.read_bytes()).hexdigest()
        args.checksum.write_text(f"{digest}  {args.feed.name}\n", encoding="ascii")
        args.marker.unlink(missing_ok=True)
        print(f"Signed {args.feed} with SHA256withRSA")
    finally:
        binary_signature.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
