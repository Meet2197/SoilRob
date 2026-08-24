"""
Harmonises variable names, units and sampling protocols
across 3 sites into one canonical schema.
"""
from datetime import datetime, timezone

CANONICAL_SCHEMA = [
    "record_id", "site_id", "sensor_type", "timestamp_utc",
    "temperature_c", "scan_angle_deg", "range_m", "roughness_cm",
    "error_code", "warning_code", "latitude", "longitude",
    "elevation_m", "crs",
]

# Per-site raw field name -> canonical field name
SITE_FIELD_MAP = {
    "site_A": {
        "temp_f": "temperature_c",
        "Oeffnungswinkel": "scan_angle_deg",
        "Fehlercode_Sensor": "error_code",
        "Warnungscode_Sensor": "warning_code",
        "Roughness_1": "roughness_cm",
    },
    "site_B": {
        "thermal_temperature": "temperature_c",   # already Celsius
        "lidar_open_angle": "scan_angle_deg",
        "lidar_err": "error_code",
        "lidar_warn": "warning_code",
        "roughness_mm": "roughness_cm",           # needs mm->cm
    },
    "site_C": {
        "cam_temp_k": "temperature_c",            # Kelvin -> Celsius
        "angle_raw": "scan_angle_deg",            # 0-255 -> 0-255 deg (1:1 per datasheet)
        "error_flags": "error_code",
        "warn_flags": "warning_code",
        "surface_roughness_cm": "roughness_cm",
    },
}

# Unit conversion registered by (source_field, target_field)
UNIT_CONVERSIONS = {
    "temp_f": lambda v: (v - 32) * 5.0 / 9.0,
    "cam_temp_k": lambda v: v - 273.15,
    "roughness_mm": lambda v: v / 10.0,
}

SAMPLING_PROTOCOLS = {
    # documents each site's native acquisition rate/mode for provenance
    "site_A": {"thermal_hz": 1, "lidar_report_ms": 200, "mode": "snapshot"},
    "site_B": {"thermal_hz": 1, "lidar_report_ms": 200, "mode": "line-scan"},
    "site_C": {"thermal_hz": 1, "lidar_report_ms": 200, "mode": "snapshot"},
}


def harmonize(raw: dict, site_id: str, sensor_type: str, crs: str) -> dict:
    """Map + convert one raw sensor reading into the canonical schema."""
    mapping = SITE_FIELD_MAP.get(site_id, {})
    out = {k: None for k in CANONICAL_SCHEMA}
    out["site_id"] = site_id
    out["sensor_type"] = sensor_type
    out["timestamp_utc"] = raw.get("timestamp_utc", datetime.now(timezone.utc).timestamp())
    out["crs"] = crs
    out["record_id"] = f"{site_id}_{sensor_type}_{out['timestamp_utc']}"

    for raw_field, value in raw.items():
        canon = mapping.get(raw_field)
        if canon is None:
            continue
        if raw_field in UNIT_CONVERSIONS and value is not None:
            value = UNIT_CONVERSIONS[raw_field](value)
        out[canon] = value

    # pass through geolocation if already canonical
    for f in ("latitude", "longitude", "elevation_m"):
        if f in raw:
            out[f] = raw[f]

    return out