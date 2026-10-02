"""
Automated QA protocol: completeness, outlier detection,
CRS validation, temporal consistency.
Sensor-agnostic - works for thermal, HSI, or any fused record.
"""
from __future__ import annotations
import pandas as pd
from pyproj import CRS
from datetime import datetime, timezone


def check_completeness(record: dict, required_fields: list[str]) -> dict:
    missing = [f for f in required_fields if record.get(f) is None]
    ratio_present = 1 - len(missing) / len(required_fields) if required_fields else 1.0
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


def check_temperature_bounds(record: dict, qa_config: dict) -> dict:
    temp = record.get("temperature_c")
    if temp is None:
        return {"check": "temperature_bounds", "passed": False, "value": None, "reason": "missing temperature_c"}

    lower = qa_config.get("min_temperature_c")
    upper = qa_config.get("max_temperature_c")
    passed = True
    if lower is not None and temp < lower:
        passed = False
    if upper is not None and temp > upper:
        passed = False
    return {
        "check": "temperature_bounds",
        "passed": passed,
        "value": temp,
        "min_temperature_c": lower,
        "max_temperature_c": upper,
    }


def check_missing_fraction(history: pd.Series, qa_config: dict) -> dict:
    max_missing_fraction = qa_config.get("max_missing_fraction", 0.05)
    if history.empty:
        return {"check": "missing_fraction", "passed": True, "missing_fraction": 0.0}
    missing = float(history.isna().mean())
    return {
        "check": "missing_fraction",
        "passed": missing <= max_missing_fraction,
        "missing_fraction": round(missing, 3),
        "max_missing_fraction": max_missing_fraction,
    }


def check_jump_limit(record: dict, history: pd.Series, qa_config: dict) -> dict:
    max_jump_c = qa_config.get("max_jump_c")
    current = record.get("temperature_c")
    if max_jump_c is None or current is None or history.empty:
        return {"check": "jump_limit", "passed": True, "max_jump_c": max_jump_c}
    last_valid = history.dropna().iloc[-1] if not history.dropna().empty else None
    if last_valid is None:
        return {"check": "jump_limit", "passed": True, "max_jump_c": max_jump_c}
    delta = abs(float(current) - float(last_valid))
    return {
        "check": "jump_limit",
        "passed": delta <= max_jump_c,
        "delta_c": round(delta, 3),
        "max_jump_c": max_jump_c,
    }


def check_rate_limit(record: dict, history: pd.Series, qa_config: dict) -> dict:
    max_rate_c_per_s = qa_config.get("max_rate_c_per_s")
    current = record.get("temperature_c")
    current_ts = record.get("timestamp_utc")
    if max_rate_c_per_s is None or current is None or current_ts is None or history.empty:
        return {"check": "rate_limit", "passed": True, "max_rate_c_per_s": max_rate_c_per_s}
    recent = history.dropna()
    if recent.empty:
        return {"check": "rate_limit", "passed": True, "max_rate_c_per_s": max_rate_c_per_s}
    last_temp = float(recent.iloc[-1])
    last_ts = record.get("last_timestamp_utc") or (history.index[-1] if hasattr(history, 'index') else None)
    if last_ts is None:
        return {"check": "rate_limit", "passed": True, "max_rate_c_per_s": max_rate_c_per_s}
    dt = float(current_ts) - float(last_ts)
    if dt <= 0 or not pd.notnull(dt):
        return {"check": "rate_limit", "passed": True, "max_rate_c_per_s": max_rate_c_per_s}
    rate = abs(float(current) - last_temp) / dt
    return {
        "check": "rate_limit",
        "passed": rate <= max_rate_c_per_s,
        "rate_c_per_s": round(rate, 3),
        "max_rate_c_per_s": max_rate_c_per_s,
    }


def validate_crs(crs_str: str, expected: str = "EPSG:4326") -> dict:
    try:
        actual = CRS.from_user_input(crs_str)
        expected_crs = CRS.from_user_input(expected)
        ok = actual.equals(expected_crs) or actual.to_epsg() == expected_crs.to_epsg()
        return {"check": "crs_validation", "passed": ok, "crs_found": str(actual)}
    except Exception as e:
        return {"check": "crs_validation", "passed": False, "error": str(e)}


def check_temporal_consistency(last_ts: float | None, current_ts: float, max_gap_s: float = 10.0) -> dict:
    if last_ts is None:
        return {"check": "temporal_consistency", "passed": True, "gap_s": None}
    gap = current_ts - last_ts
    passed = 0 <= gap <= max_gap_s * 10
    return {"check": "temporal_consistency", "passed": passed, "gap_s": round(gap, 3)}


def run_qa_pipeline(record: dict, history: pd.DataFrame, config: dict, last_ts: float | None,
                     required_fields: list[str], numeric_field: str) -> dict:
    """Runs all QA checks and returns a structured report + overall pass/fail."""
    site_cfg = config.get("sites", {}).get(record.get("site_id"), {})
    qa_config = config.get("qa", {}) if config.get("qa") else site_cfg.get("thermal", {}).get("qa", {})
    if not qa_config and record.get("sensor_type") == "fused_thermal_hsi":
        qa_config = site_cfg.get("thermal", {}).get("qa", {})

    history_series = history[numeric_field] if numeric_field in history.columns else pd.Series(dtype=float)
    results = []
    results.append(check_completeness(record, required_fields))
    results.append(check_temperature_bounds(record, qa_config))
    results.append(check_missing_fraction(history_series, qa_config))
    results.append(check_jump_limit(record, history_series, qa_config))
    results.append(check_rate_limit(record, history_series, qa_config))
    results.append(check_outlier(
        record, numeric_field,
        history_series,
        method=qa_config.get("outlier_method", "iqr"), k=qa_config.get("outlier_k", 1.5)
    ))
    expected_crs = qa_config.get("expected_crs", site_cfg.get("crs_native", "EPSG:4326"))
    results.append(validate_crs(record.get("crs", "EPSG:4326"), expected_crs))
    results.append(check_temporal_consistency(
        last_ts, record.get("timestamp_utc"), qa_config.get("max_temporal_gap_s", 10.0)
    ))

    overall_pass = all(r["passed"] for r in results)
    return {
        "record_id": record.get("record_id"),
        "site_id": record.get("site_id"),
        "timestamp_checked": datetime.now(timezone.utc).isoformat(),
        "overall_pass": overall_pass,
        "checks": results,
    }