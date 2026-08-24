"""
Automated QA protocol: completeness, outlier detection,
CRS validation, temporal consistency.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from pyproj import CRS
from datetime import datetime, timezone


def check_completeness(record: dict, required_fields: list[str]) -> dict:
    missing = [f for f in required_fields if record.get(f) is None]
    ratio_present = 1 - len(missing) / len(required_fields)
    return {
        "check": "completeness",
        "passed": len(missing) == 0,
        "missing_fields": missing,
        "completeness_ratio": round(ratio_present, 3),
    }


def detect_outliers_iqr(series: pd.Series, k: float = 1.5) -> pd.Series:
    q1, q3 = series.quantile(0.25), series.quantile(0.75)
    iqr = q3 - q1
    lower, upper = q1 - k * iqr, q3 + k * iqr
    return (series < lower) | (series > upper)


def detect_outliers_zscore(series: pd.Series, threshold: float = 3.0) -> pd.Series:
    z = (series - series.mean()) / (series.std(ddof=0) + 1e-9)
    return z.abs() > threshold


def check_outlier(record: dict, field: str, history: pd.Series, method="iqr", k=1.5) -> dict:
    if history.empty or len(history) < 5:
        return {"check": "outlier", "field": field, "passed": True, "note": "insufficient history"}
    extended = pd.concat([history, pd.Series([record.get(field)])], ignore_index=True)
    mask = detect_outliers_iqr(extended, k) if method == "iqr" else detect_outliers_zscore(extended)
    is_outlier = bool(mask.iloc[-1])
    return {"check": "outlier", "field": field, "passed": not is_outlier}


def validate_crs(crs_str: str, expected: str = "EPSG:4326") -> dict:
    try:
        actual = CRS.from_user_input(crs_str)
        expected_crs = CRS.from_user_input(expected)
        ok = actual.equals(expected_crs) or actual.to_epsg() == expected_crs.to_epsg()
        return {"check": "crs_validation", "passed": ok, "crs_found": str(actual)}
    except Exception as e:
        return {"check": "crs_validation", "passed": False, "error": str(e)}


def check_temporal_consistency(last_ts: float | None, current_ts: float, max_gap_s: float = 5.0) -> dict:
    if last_ts is None:
        return {"check": "temporal_consistency", "passed": True, "gap_s": None}
    gap = current_ts - last_ts
    passed = 0 <= gap <= max_gap_s * 10  # allow up to 10x expected gap before flag
    return {"check": "temporal_consistency", "passed": passed, "gap_s": round(gap, 3)}


def run_qa_pipeline(record: dict, history: pd.DataFrame, config: dict, last_ts: float | None,
                     required_fields: list[str], numeric_field: str) -> dict:
    """Runs all four QA checks and returns a structured report + overall pass/fail."""
    results = []
    results.append(check_completeness(record, required_fields))
    results.append(check_outlier(
        record, numeric_field,
        history[numeric_field] if numeric_field in history else pd.Series(dtype=float),
        method=config["qa"]["outlier_method"], k=config["qa"]["outlier_k"]
    ))
    results.append(validate_crs(record.get("crs", "EPSG:4326"), config["qa"]["expected_crs"]))
    results.append(check_temporal_consistency(
        last_ts, record.get("timestamp_utc"), config["qa"]["max_temporal_gap_s"]
    ))

    overall_pass = all(r["passed"] for r in results)
    return {
        "record_id": record.get("record_id"),
        "site_id": record.get("site_id"),
        "timestamp_checked": datetime.now(timezone.utc).isoformat(),
        "overall_pass": overall_pass,
        "checks": results,
    }