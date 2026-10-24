from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from forecast_core import build_payload, load_config, load_dataset


class SignatureRoundTripTest(unittest.TestCase):
    def test_sign_and_verify(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            temp = Path(folder)
            private_key, public_key = temp / "private.pem", temp / "public.pem"
            feed, signature = temp / "latest.json", temp / "latest.sig"
            checksum, marker = temp / "latest.sha256", temp / "signing_required"
            subprocess.run([
                "openssl", "genpkey", "-algorithm", "RSA",
                "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(private_key),
            ], check=True, capture_output=True)
            subprocess.run([
                "openssl", "pkey", "-in", str(private_key), "-pubout", "-out", str(public_key),
            ], check=True, capture_output=True)
            der = subprocess.run([
                "openssl", "pkey", "-pubin", "-in", str(public_key), "-outform", "DER",
            ], check=True, capture_output=True).stdout
            config = load_config(ROOT / "config/model_config.json")
            config["signing"]["public_key_sha256"] = hashlib.sha256(der).hexdigest()
            dataset = ROOT / "data/da_ncr_weekly_verified.csv"
            payload = build_payload(
                load_dataset(dataset), config, dataset,
                generated_at=datetime(2026, 10, 24, tzinfo=timezone.utc))
            feed.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            marker.write_text("test\n", encoding="utf-8")
            subprocess.run([
                sys.executable, str(ROOT / "scripts/sign_feed.py"),
                "--private-key", str(private_key), "--public-key", str(public_key),
                "--feed", str(feed), "--signature", str(signature),
                "--checksum", str(checksum), "--marker", str(marker),
            ], check=True, capture_output=True, text=True)
            verified = subprocess.run([
                sys.executable, str(ROOT / "scripts/verify_feed.py"),
                "--public-key", str(public_key), "--feed", str(feed),
                "--signature", str(signature),
            ], check=True, capture_output=True, text=True)
            self.assertIn("Verified forecast feed", verified.stdout)
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
