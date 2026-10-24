#!/usr/bin/env python3
"""Fetch official DA weekly prices and prepare a release-gated forecast payload."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from forecast_core import (SERIES_COLUMNS, build_payload, load_config,
                           load_dataset, production_health)

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/da_ncr_weekly_verified.csv"
CONFIG = ROOT / "config/model_config.json"
AUDIT = ROOT / "data/source_audit.jsonl"
HEALTH_REPORT = ROOT / "reports/production_health.json"
UPDATE_RESULT = ROOT / "state/update_result.json"
SIGNING_REQUIRED = ROOT / "state/signing_required"
FEED = ROOT / "public/forecast/latest.json"
SIGNATURE = ROOT / "public/forecast/latest.sig"
USER_AGENT = "GreenChainForecastBot/1.0 (+https://github.com/greenchain-plus/greenchain-forecast-feed)"
ALLOWED_HOST = "www.da.gov.ph"

PRICE_PATTERNS = {
    "green_leaf": re.compile(
        r"^\s*Lettuce\s*\(\s*Green\s+Ice\s*\).*?\bkg\s+([0-9][0-9,]*(?:\.[0-9]+)?)\s*$",
        re.IGNORECASE | re.MULTILINE),
    "iceberg": re.compile(
        r"^\s*Lettuce\s*\(\s*Iceberg\s*\).*?\bkg\s+([0-9][0-9,]*(?:\.[0-9]+)?)\s*$",
        re.IGNORECASE | re.MULTILINE),
    "romaine": re.compile(
        r"^\s*Lettuce\s*\(\s*Romaine\s*\).*?\bkg\s+([0-9][0-9,]*(?:\.[0-9]+)?)\s*$",
        re.IGNORECASE | re.MULTILINE),
}
PERIOD_PATTERN = re.compile(
    r"For\s+the\s+period\s+of\s+([A-Za-z]+)\s+(\d{1,2})\s*-\s*"
    r"(?:([A-Za-z]+)\s+)?(\d{1,2})\s*,\s*(\d{4})",
    re.IGNORECASE)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_official_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
        raise ValueError(f"URL is not an approved HTTPS DA source: {url}")


def download(url: str, maximum_bytes: int) -> tuple[bytes, str, str]:
    ensure_official_url(url)
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/pdf;q=0.9,*/*;q=0.5",
            })
            with urllib.request.urlopen(request, timeout=60) as response:
                final_url = response.geturl()
                ensure_official_url(final_url)
                data = response.read(maximum_bytes + 1)
                content_type = response.headers.get("Content-Type", "")
            if len(data) > maximum_bytes:
                raise ValueError(f"download exceeded {maximum_bytes} bytes")
            return data, final_url, content_type
        except Exception as error:
            last_error = error
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"failed to download {url}: {last_error}")


def weekly_pdf_links(listing_html: str, listing_url: str) -> list[str]:
    hrefs = re.findall(r"href\s*=\s*[\"']([^\"']+?\.pdf(?:\?[^\"']*)?)[\"']",
                       listing_html, flags=re.IGNORECASE)
    links: list[str] = []
    for href in hrefs:
        url = urllib.parse.urljoin(listing_url, html.unescape(href))
        clean = urllib.parse.urlunparse(urllib.parse.urlparse(url)._replace(query="", fragment=""))
        if "weekly-average-price" not in clean.lower():
            continue
        try:
            ensure_official_url(clean)
        except ValueError:
            continue
        if clean not in links:
            links.append(clean)
    if not links:
        raise ValueError("the DA listing contained no weekly-average-price PDF links")
    return links


def pdf_to_text(pdf: bytes) -> str:
    if not pdf.startswith(b"%PDF-"):
        raise ValueError("downloaded document does not have a PDF header")
    temporary = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    path = Path(temporary.name)
    try:
        temporary.write(pdf)
        temporary.close()
        process = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            capture_output=True, text=True, timeout=60, check=False)
        if process.returncode != 0:
            raise RuntimeError(f"pdftotext failed: {process.stderr.strip()}")
        if len(process.stdout.strip()) < 100:
            raise ValueError("the DA PDF did not contain extractable text")
        return process.stdout
    finally:
        path.unlink(missing_ok=True)


def parse_report_text(text: str, source_url: str, pdf_sha256: str) -> dict[str, Any]:
    normalized = text.replace("–", "-").replace("—", "-")
    period = PERIOD_PATTERN.search(normalized)
    if not period:
        raise ValueError("could not find the DA report period")
    month_name, start_day, end_month, _end_day, year = period.groups()
    report_year = int(year)
    if end_month:
        start_month_number = datetime.strptime(month_name, "%B").month
        end_month_number = datetime.strptime(end_month, "%B").month
        if start_month_number > end_month_number:
            report_year -= 1
    period_start = datetime.strptime(
        f"{month_name} {start_day} {report_year}", "%B %d %Y").date()
    if period_start.weekday() != 0:
        raise ValueError(f"DA report period does not start on Monday: {period_start}")
    report: dict[str, Any] = {
        "period_start": period_start,
        "source_url": source_url,
        "source_sha256": pdf_sha256,
    }
    for name, pattern in PRICE_PATTERNS.items():
        matches = pattern.findall(normalized)
        if len(matches) != 1:
            raise ValueError(f"expected exactly one {name} price, found {len(matches)}")
        report[name] = float(matches[0].replace(",", ""))
    return report


def fetch_report(url: str) -> dict[str, Any]:
    pdf, final_url, content_type = download(url, 20 * 1024 * 1024)
    if "pdf" not in content_type.lower() and not pdf.startswith(b"%PDF-"):
        raise ValueError(f"DA weekly report was not a PDF: {content_type}")
    digest = hashlib.sha256(pdf).hexdigest()
    return parse_report_text(pdf_to_text(pdf), final_url, digest)


def discover_reports(listing_url: str, latest: date, override_pdf: str | None) -> list[dict[str, Any]]:
    if override_pdf:
        report = fetch_report(override_pdf)
        return [] if report["period_start"] <= latest else [report]
    body, final_url, _content_type = download(listing_url, 5 * 1024 * 1024)
    links = weekly_pdf_links(body.decode("utf-8", errors="replace"), final_url)
    reports: list[dict[str, Any]] = []
    for link in links[:20]:
        report = fetch_report(link)
        if report["period_start"] <= latest:
            break
        reports.append(report)
    reports.sort(key=lambda report: report["period_start"])
    return reports


def validate_new_reports(existing: list[dict[str, Any]], reports: list[dict[str, Any]],
                         config: dict[str, Any]) -> None:
    if not reports:
        return
    expected = existing[-1]["period_start"]
    previous = existing[-1]
    limits = config["input_validation"]
    minimum = float(limits["minimum_php_per_kg"])
    maximum = float(limits["maximum_php_per_kg"])
    maximum_ratio = float(limits["maximum_weekly_ratio"])
    seen: set[date] = set()
    for report in reports:
        expected += timedelta(days=7)
        if report["period_start"] != expected:
            raise ValueError(f"expected weekly report {expected}, found {report['period_start']}")
        if report["period_start"] in seen:
            raise ValueError(f"duplicate discovered report {report['period_start']}")
        seen.add(report["period_start"])
        for name in SERIES_COLUMNS:
            value = float(report[name])
            if not minimum <= value <= maximum:
                raise ValueError(f"{name} price {value} is outside the configured range")
            ratio = value / float(previous[name])
            if ratio > maximum_ratio or ratio < 1.0 / maximum_ratio:
                raise ValueError(f"{name} weekly ratio {ratio:.3f} requires manual review")
        previous = report


def save_dataset(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(".tmp")
    fieldnames = ["period_start", *SERIES_COLUMNS.values(), "source_url"]
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            rendered: dict[str, Any] = {
                "period_start": row["period_start"].isoformat(),
                "source_url": row["source_url"],
            }
            for name, column in SERIES_COLUMNS.items():
                rendered[column] = f"{float(row[name]):.2f}"
            writer.writerow(rendered)
    temporary.replace(path)


def append_audit(path: Path, reports: list[dict[str, Any]]) -> None:
    if not reports:
        return
    with path.open("a", encoding="utf-8") as stream:
        for report in reports:
            record = {
                "period_start": report["period_start"].isoformat(),
                "source_url": report["source_url"],
                "source_sha256": report["source_sha256"],
                "verified_at": utc_now(),
                "prices_php_per_kg": {name: round(float(report[name]), 2)
                                      for name in SERIES_COLUMNS},
            }
            stream.write(json.dumps(record, sort_keys=True) + "\n")


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def latest_audit_sha(path: Path, period_start: date) -> str | None:
    if not path.exists():
        return None
    result = None
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("period_start") == period_start.isoformat():
            result = record.get("source_sha256")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listing-url", default="https://www.da.gov.ph/price-monitoring/")
    parser.add_argument("--pdf-url", default="", help="Optional official DA PDF override")
    parser.add_argument("--skip-fetch", action="store_true", help="Build only from the verified seed data")
    args = parser.parse_args()
    config = load_config(CONFIG)
    existing = load_dataset(DATASET)
    reports: list[dict[str, Any]] = []
    if not args.skip_fetch:
        reports = discover_reports(args.listing_url, existing[-1]["period_start"],
                                   args.pdf_url.strip() or None)
        validate_new_reports(existing, reports, config)
    if reports:
        save_dataset(DATASET, existing + reports)
        append_audit(AUDIT, reports)
    rows = load_dataset(DATASET)
    health = production_health(rows, config)
    write_json(HEALTH_REPORT, health)
    signed_feed_exists = FEED.exists() and SIGNATURE.exists()
    publish_required = bool(reports) or not signed_feed_exists
    if health["status"] != "HEALTHY":
        status = "DRIFT_BLOCKED"
        publish_required = False
        if not signed_feed_exists:
            raise RuntimeError("health gates blocked the initial forecast publication")
    elif publish_required:
        source_hash = latest_audit_sha(AUDIT, rows[-1]["period_start"])
        write_json(FEED, build_payload(rows, config, DATASET, source_hash))
        SIGNING_REQUIRED.write_text("sign latest.json\n", encoding="utf-8")
        status = "PUBLISHED" if reports else "BOOTSTRAPPED"
    else:
        status = "NO_NEW_REPORT"
    result = {
        "status": status,
        "checked_at": utc_now(),
        "reports_added": len(reports),
        "data_through": rows[-1]["period_start"].isoformat(),
        "verified_weeks": len(rows),
        "publication_changed": publish_required,
        "production_health": health["status"],
    }
    write_json(UPDATE_RESULT, result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
