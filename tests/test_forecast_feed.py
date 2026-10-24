from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from forecast_core import build_payload, load_config, load_dataset, production_health
from update_weekly import parse_report_text, validate_new_reports, weekly_pdf_links


class ForecastFeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset_path = ROOT / "data/da_ncr_weekly_verified.csv"
        cls.config = load_config(ROOT / "config/model_config.json")
        cls.rows = load_dataset(cls.dataset_path)

    def test_seed_dataset_and_release_predictions(self) -> None:
        self.assertEqual(42, len(self.rows))
        payload = build_payload(self.rows, self.config, self.dataset_path)
        self.assertEqual(197.94, payload["predictions"]["green_leaf"]["point_php_per_kg"])
        self.assertEqual(287.81, payload["predictions"]["iceberg"]["point_php_per_kg"])
        self.assertEqual(173.50, payload["predictions"]["romaine"]["point_php_per_kg"])
        self.assertEqual("2026-10-19", payload["forecast_period"]["start"])
        self.assertEqual("2026-10-25", payload["forecast_period"]["end"])

    def test_production_health_passes_locked_window(self) -> None:
        health = production_health(self.rows, self.config)
        self.assertEqual("HEALTHY", health["status"])
        self.assertAlmostEqual(9.1608, health["aggregate"]["wape_percent"], places=4)
        self.assertAlmostEqual(0.8725, health["aggregate"]["mase"], places=4)
        self.assertTrue(all(health["gates"].values()))

    def test_official_report_parser(self) -> None:
        text = (ROOT / "tests/fixtures/sample_da_report.txt").read_text(encoding="utf-8")
        report = parse_report_text(
            text, "https://www.da.gov.ph/wp-content/uploads/2026/10/test.pdf", "a" * 64)
        self.assertEqual(date(2026, 10, 12), report["period_start"])
        self.assertEqual(220.21, report["green_leaf"])
        self.assertEqual(324.76, report["iceberg"])
        self.assertEqual(206.16, report["romaine"])

    def test_cross_year_period(self) -> None:
        text = (ROOT / "tests/fixtures/sample_da_report.txt").read_text(encoding="utf-8")
        text = text.replace("For the period of October 12-18, 2026",
                            "For the period of December 28-January 3, 2027")
        report = parse_report_text(
            text, "https://www.da.gov.ph/wp-content/uploads/2027/01/test.pdf", "b" * 64)
        self.assertEqual(date(2026, 12, 28), report["period_start"])

    def test_listing_filters_non_weekly_documents(self) -> None:
        page = """
        <a href="https://www.da.gov.ph/wp-content/uploads/2026/10/Weekly-Average-Prices-October-12-18-2026.pdf">weekly</a>
        <a href="https://www.da.gov.ph/wp-content/uploads/2026/10/unrelated.pdf">other</a>
        """
        self.assertEqual(1, len(weekly_pdf_links(
            page, "https://www.da.gov.ph/price-monitoring/")))

    def test_gap_and_outlier_are_rejected(self) -> None:
        report = {
            "period_start": date(2026, 10, 26),
            "green_leaf": 210.0, "iceberg": 310.0, "romaine": 205.0,
            "source_url": "https://www.da.gov.ph/wp-content/uploads/test.pdf",
            "source_sha256": "c" * 64,
        }
        with self.assertRaisesRegex(ValueError, "expected weekly report"):
            validate_new_reports(self.rows, [report], self.config)
        report["period_start"] = date(2026, 10, 19)
        report["green_leaf"] = 1499.0
        with self.assertRaisesRegex(ValueError, "weekly ratio"):
            validate_new_reports(self.rows, [report], self.config)

    def test_key_fingerprint(self) -> None:
        self.assertEqual(
            "6b32c6b62e4c687dbbfd93b0aec7e9167289a2bacbb60e74eeefb44d8b5b76b1",
            self.config["signing"]["public_key_sha256"])


if __name__ == "__main__":
    unittest.main()
