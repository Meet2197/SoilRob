"""
Harmonises variable names, units and sampling protocols
across 3 sites into one canonical schema.
Covers Thermal (FLIR AX8) and Hyperspectral (HAIP BlackBullet V2) only.
"""
from datetime import datetime, timezone

CANONICAL_SCHEMA = [
    "record_id", "site_id", "sensor_type", "timestamp_utc",
    "temperature_c", "hsi_gain", "hsi_exposure_us",
    "hsi_serial_number", "hsi_image_path",
    "latitude", "longitude", "elevation_m", "crs",
]

# Per-site raw field name -> canonical field name
SITE_FIELD_MAP = {
    "site_A": {
        "temp_f": "temperature_c",
        "gain": "hsi_gain",
        "exposure_us": "hsi_exposure_us",
        "serial_number": "hsi_serial_number",
        "image_path": "hsi_image_path",
    },
    "site_B": {
        "thermal_temperature": "temperature_c",   # already Celsius
        "gain": "hsi_gain",
        "exposure_us": "hsi_exposure_us",
        "serial_number": "hsi_serial_number",
        "image_path": "hsi_image_path",
    },
    "site_C": {
        "cam_temp_k": "temperature_c",            # Kelvin -> Celsius
        "gain": "hsi_gain",
        "exposure_us": "hsi_exposure_us",
        "serial_number": "hsi_serial_number",
        "image_path": "hsi_image_path",
    },
}

# Unit conversion registered by source_field
UNIT_CONVERSIONS = {
    "temp_f": lambda v: (v - 32) * 5.0 / 9.0,
    "cam_temp_k": lambda v: v - 273.15,
}

SAMPLING_PROTOCOLS = {
    # documents each site's native acquisition rate/mode for provenance
    "site_A": {"thermal_hz": 1, "hsi_mode": "snapshot"},
    "site_B": {"thermal_hz": 1, "hsi_mode": "line-scan"},
    "site_C": {"thermal_hz": 1, "hsi_mode": "snapshot"},
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

    for f in ("latitude", "longitude", "elevation_m"):
        if f in raw:
            out[f] = raw[f]

    return out