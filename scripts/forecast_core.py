#!/usr/bin/env python3
"""Dependency-free production calculations for the Green CHAIN forecast feed."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SERIES_COLUMNS = {
    "green_leaf": "green_leaf_php_per_kg",
    "iceberg": "iceberg_php_per_kg",
    "romaine": "romaine_php_per_kg",
}
SERIES_LABELS = {
    "green_leaf": "Green Leaf",
    "iceberg": "Iceberg",
    "romaine": "Romaine",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_dataset(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as stream:
        raw_rows = list(csv.DictReader(stream))
    if len(raw_rows) < 40:
        raise ValueError("at least 40 verified weekly observations are required")
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        period_start = date.fromisoformat(raw["period_start"])
        source_url = raw["source_url"].strip()
        if not source_url.startswith("https://www.da.gov.ph/"):
            raise ValueError(f"non-DA source URL for {period_start}")
        row: dict[str, Any] = {"period_start": period_start, "source_url": source_url}
        for name, column in SERIES_COLUMNS.items():
            value = float(raw[column])
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"invalid {name} price for {period_start}")
            row[name] = value
        rows.append(row)
    dates = [row["period_start"] for row in rows]
    if len(set(dates)) != len(dates):
        raise ValueError("duplicate weekly observation")
    if dates != sorted(dates):
        raise ValueError("weekly observations are not sorted")
    for left, right in zip(dates, dates[1:]):
        if right - left != timedelta(days=7):
            raise ValueError(f"weekly gap between {left} and {right}")
    return rows


def forecast(previous: float, latest: float, alpha: float) -> float:
    return max(0.0, latest + alpha * (latest - previous))


def seasonal_scale(values: list[float], season: int = 4) -> float:
    if len(values) <= season:
        raise ValueError("not enough values for seasonal scale")
    differences = [abs(values[index] - values[index - season])
                   for index in range(season, len(values))]
    return sum(differences) / len(differences)


def calculate_metrics(actual: list[float], predicted: list[float], scale: float) -> dict[str, Any]:
    if not actual or len(actual) != len(predicted):
        raise ValueError("actual and predicted must be non-empty and equal length")
    errors = [prediction - observation for observation, prediction in zip(actual, predicted)]
    absolute = [abs(error) for error in errors]
    mae = sum(absolute) / len(absolute)
    actual_total = sum(abs(value) for value in actual)
    rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
    smape_parts = [200.0 * abs(prediction - observation)
                   / (abs(observation) + abs(prediction))
                   for observation, prediction in zip(actual, predicted)
                   if abs(observation) + abs(prediction) > 0]
    return {
        "rows": len(actual),
        "mae_php_per_kg": round(mae, 4),
        "wape_percent": round(100.0 * sum(absolute) / actual_total, 4),
        "rmse_php_per_kg": round(rmse, 4),
        "smape_percent": round(sum(smape_parts) / len(smape_parts), 4),
        "mase": round(mae / scale, 4),
    }


def production_health(rows: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    alpha = float(config["alpha"])
    requested = int(config["production_gates"]["rolling_weeks"])
    window = min(requested, len(rows) - 8)
    if window < 4:
        raise ValueError("not enough history for production monitoring")
    start = len(rows) - window
    actual_all: list[float] = []
    predicted_all: list[float] = []
    baseline_all: list[float] = []
    scales: list[float] = []
    by_variety: dict[str, Any] = {}
    baseline_by_variety: dict[str, Any] = {}
    for name in SERIES_COLUMNS:
        values = [float(row[name]) for row in rows]
        actual = values[start:]
        predicted = [forecast(values[index - 2], values[index - 1], alpha)
                     for index in range(start, len(values))]
        baseline = [values[index - 1] for index in range(start, len(values))]
        scale = seasonal_scale(values[:start], 4)
        scales.append(scale)
        by_variety[name] = calculate_metrics(actual, predicted, scale)
        baseline_by_variety[name] = calculate_metrics(actual, baseline, scale)
        actual_all.extend(actual)
        predicted_all.extend(predicted)
        baseline_all.extend(baseline)
    aggregate_scale = sum(scales) / len(scales)
    aggregate = calculate_metrics(actual_all, predicted_all, aggregate_scale)
    baseline = calculate_metrics(actual_all, baseline_all, aggregate_scale)
    gates_config = config["production_gates"]
    gates = {
        "aggregate_wape_within_limit": aggregate["wape_percent"]
        <= float(gates_config["maximum_aggregate_wape_percent"]),
        "aggregate_mase_below_one": aggregate["mase"]
        < float(gates_config["maximum_aggregate_mase"]),
        "every_variety_wape_within_limit": all(
            metrics["wape_percent"] <= float(gates_config["maximum_variety_wape_percent"])
            for metrics in by_variety.values()),
        "beats_previous_week_baseline": aggregate["wape_percent"] < baseline["wape_percent"],
    }
    return {
        "status": "HEALTHY" if all(gates.values()) else "REVIEW_REQUIRED",
        "window_weeks": window,
        "period_start": rows[start]["period_start"].isoformat(),
        "period_end": rows[-1]["period_start"].isoformat(),
        "aggregate": aggregate,
        "by_variety": by_variety,
        "previous_week_baseline": {
            "aggregate": baseline,
            "by_variety": baseline_by_variety,
        },
        "gates": gates,
    }


def build_payload(rows: list[dict[str, Any]], config: dict[str, Any], dataset_path: Path,
                  source_sha256: str | None = None,
                  generated_at: datetime | None = None) -> dict[str, Any]:
    health = production_health(rows, config)
    if health["status"] != "HEALTHY":
        raise ValueError("production health gates do not permit publication")
    generated = generated_at or datetime.now(timezone.utc)
    latest = rows[-1]
    previous = rows[-2]
    next_week = latest["period_start"] + timedelta(days=7)
    period_end = next_week + timedelta(days=6)
    predictions: dict[str, Any] = {}
    for name in SERIES_COLUMNS:
        point = forecast(float(previous[name]), float(latest[name]), float(config["alpha"]))
        band = float(config["error_band_php_per_kg"][name])
        predictions[name] = {
            "label": SERIES_LABELS[name],
            "point_php_per_kg": round(point, 2),
            "lower_php_per_kg": round(max(0.0, point - band), 2),
            "upper_php_per_kg": round(point + band, 2),
            "latest_observed_php_per_kg": round(float(latest[name]), 2),
            "previous_observed_php_per_kg": round(float(previous[name]), 2),
        }
    return {
        "schema_version": 1,
        "feed_id": "greenchain-weekly-lettuce-price-forecast",
        "sequence": len(rows),
        "generated_at": generated.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "model": {
            "id": config["model_id"],
            "release_status": config["release_status"],
            "algorithm": config["algorithm"],
            "alpha": config["alpha"],
            "original_release_validation": config["release_validation"],
        },
        "scope": {
            "market": config["market_scope"],
            "region": "NCR",
            "price_level": "RETAIL_REFERENCE",
            "currency": config["currency"],
            "unit": config["unit"],
        },
        "data": {
            "verified_weeks": len(rows),
            "period_start": rows[0]["period_start"].isoformat(),
            "data_through": latest["period_start"].isoformat(),
            "dataset_sha256": sha256_file(dataset_path),
            "latest_source_url": latest["source_url"],
            "latest_source_sha256": source_sha256,
            "source_listing": config["source_listing"],
        },
        "forecast_period": {
            "start": next_week.isoformat(),
            "end": period_end.isoformat(),
            "stale_after": (period_end + timedelta(days=7)).isoformat(),
        },
        "predictions": predictions,
        "production_health": health,
        "signature": {
            "algorithm": config["signing"]["algorithm"],
            "public_key_sha256": config["signing"]["public_key_sha256"],
            "detached_file": "latest.sig",
        },
        "limitations": [
            "NCR retail reference only; not a farm-gate or Iligan City quotation",
            "Forecast ranges are empirical error bands, not guarantees",
            "The last verified forecast remains active when source or model-health checks fail",
        ],
    }
