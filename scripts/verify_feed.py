#!/usr/bin/env python3
"""Verify feed schema, checksum, pinned key fingerprint, and detached signature."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-key", type=Path, default=ROOT / "keys/forecast_public.pem")
    parser.add_argument("--feed", type=Path, default=ROOT / "public/forecast/latest.json")
    parser.add_argument("--signature", type=Path, default=ROOT / "public/forecast/latest.sig")
    args = parser.parse_args()
    payload = json.loads(args.feed.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported forecast feed schema")
    if payload.get("model", {}).get("release_status") != "APPROVED":
        raise ValueError("feed model is not approved")
    if payload.get("production_health", {}).get("status") != "HEALTHY":
        raise ValueError("feed production health is not healthy")
    predictions = payload.get("predictions", {})
    if set(predictions) != {"green_leaf", "iceberg", "romaine"}:
        raise ValueError("feed does not contain the three supported varieties")
    der = subprocess.run(
        ["openssl", "pkey", "-pubin", "-in", str(args.public_key), "-outform", "DER"],
        capture_output=True, check=False)
    if der.returncode != 0:
        raise RuntimeError(der.stderr.decode("utf-8", errors="replace"))
    fingerprint = hashlib.sha256(der.stdout).hexdigest()
    pinned = payload.get("signature", {}).get("public_key_sha256")
    if fingerprint != pinned:
        raise ValueError(f"public-key fingerprint mismatch: {fingerprint} != {pinned}")
    try:
        signature_bytes = base64.b64decode(
            args.signature.read_text(encoding="ascii").strip(), validate=True)
    except Exception as error:
        raise ValueError("detached signature is not valid Base64") from error
    with tempfile.NamedTemporaryFile(suffix=".sig", delete=False) as temporary:
        signature_path = Path(temporary.name)
        temporary.write(signature_bytes)
    try:
        verification = subprocess.run(
            ["openssl", "dgst", "-sha256", "-verify", str(args.public_key),
             "-signature", str(signature_path), str(args.feed)],
            capture_output=True, text=True, check=False)
        if verification.returncode != 0 or "Verified OK" not in verification.stdout:
            raise ValueError("forecast signature verification failed")
    finally:
        signature_path.unlink(missing_ok=True)
    print(f"Verified forecast feed: sequence {payload['sequence']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
