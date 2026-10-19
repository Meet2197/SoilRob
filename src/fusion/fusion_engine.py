import json
import math
import threading
from collections import deque
from pathlib import Path
import pandas as pd
from src.qa.qa_protocol import run_qa_pipeline
from src.semantic.alignment import harmonize


class FusionEngine:
    def __init__(self, config: dict):
        self.config = config
        self.tolerance_s = config["fusion"]["time_tolerance_s"]
        bufsize = config["fusion"]["buffer_size"]
        self.thermal_buffer: dict[str, deque] = {}
        self.hsi_buffer: dict[str, deque] = {}
        self.fused_buffer: deque = deque(maxlen=bufsize)
        self.quarantine_buffer: deque = deque(maxlen=bufsize)
        self.qa_reports: deque = deque(maxlen=bufsize)
        self._last_ts: dict[str, float] = {}
        self.lock = threading.Lock()

    def _buf(self, store: dict, site_id: str) -> deque:
        if site_id not in store:
            store[site_id] = deque(maxlen=self.config["fusion"]["buffer_size"])
        return store[site_id]

    def _sensor_dirs(self, site_id: str, sensor_type: str) -> tuple[Path, Path]:
        site_cfg = self.config.get("sites", {}).get(site_id, {})
        sensor_cfg = site_cfg.get(sensor_type, {})
        temp_dir = Path(sensor_cfg.get("temporary_dir", f"data/{sensor_type}_temp/{site_id}"))
        eval_dir = Path(sensor_cfg.get("evaluation_dir", f"data/{sensor_type}_evaluation/{site_id}"))
        temp_dir.mkdir(parents=True, exist_ok=True)
        eval_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir, eval_dir

    def _persist_raw_record(self, site_id: str, sensor_type: str, raw: dict) -> None:
        temp_dir, _ = self._sensor_dirs(site_id, sensor_type)
        timestamp = raw.get("timestamp_utc") or 0.0
        filename = f"{sensor_type}_{int(float(timestamp) * 1000)}.json"
        with (temp_dir / filename).open("w", encoding="utf-8") as handle:
            json.dump(raw, handle, sort_keys=True, indent=2)
        self.export_site_qa_log(site_id, sensor_type)

    def export_site_qa_log(self, site_id: str, sensor_type: str) -> pd.DataFrame:
        temp_dir, eval_dir = self._sensor_dirs(site_id, sensor_type)
        source_dir = temp_dir
        rows = []
        for json_path in sorted(source_dir.glob("*.json")):
            try:
                with json_path.open("r", encoding="utf-8") as handle:
                    raw = json.load(handle)
            except (json.JSONDecodeError, OSError):
                continue

            timestamp = raw.get("timestamp_utc")
            if raw.get("temperature_c") is not None:
                temp_value = float(raw["temperature_c"])
            elif raw.get("thermal_temperature") is not None:
                temp_value = float(raw["thermal_temperature"])
            elif raw.get("temp_f") is not None:
                temp_value = (float(raw["temp_f"]) - 32.0) * 5.0 / 9.0
            else:
                temp_value = None
            qa_cfg = self.config.get("sites", {}).get(site_id, {}).get(sensor_type, {}).get("qa", {})
            if not qa_cfg:
                qa_cfg = self.config.get("qa", {})

            passed = True
            summary_parts = []
            if temp_value is not None:
                lower = qa_cfg.get("min_temperature_c")
                upper = qa_cfg.get("max_temperature_c")
                if lower is not None and temp_value < lower:
                    passed = False
                    summary_parts.append(f"below min {lower}C")
                if upper is not None and temp_value > upper:
                    passed = False
                    summary_parts.append(f"above max {upper}C")
            if not summary_parts:
                summary_parts.append("within thresholds")

            rows.append({
                "site_id": site_id,
                "sensor_type": sensor_type,
                "timestamp_utc": timestamp,
                "record_id": raw.get("record_id") or json_path.stem,
                "temperature_c": temp_value,
                "qa_pass": passed,
                "qa_summary": "; ".join(summary_parts),
            })

        csv_path = eval_dir / f"{site_id}_{sensor_type}_qa_log.csv"
        eval_dir.mkdir(parents=True, exist_ok=True)
        frame = pd.DataFrame(rows)
        if not frame.empty:
            frame = frame.sort_values("timestamp_utc")
        frame.to_csv(csv_path, index=False)
        return frame

    def add_thermal(self, site_id: str, raw: dict, crs: str = "EPSG:4326"):
        self._persist_raw_record(site_id, "thermal", raw)
        rec = harmonize(raw, site_id, "thermal", crs)
        with self.lock:
            self._buf(self.thermal_buffer, site_id).append(rec)
            self._try_fuse(site_id)

    def add_hsi(self, site_id: str, raw: dict, crs: str = "EPSG:4326"):
        self._persist_raw_record(site_id, "hsi", raw)
        rec = harmonize(raw, site_id, "hsi", crs)
        with self.lock:
            self._buf(self.hsi_buffer, site_id).append(rec)
            self._try_fuse(site_id)

    def synchronize_stored_data(self, site_id: str) -> dict:
        """Fuse stored thermal and HSI records into the configured archive."""
        site_cfg = self.config.get("sites", {}).get(site_id)
        if site_cfg is None:
            raise ValueError(f"Unknown site: {site_id}")

        thermal_dir, _ = self._sensor_dirs(site_id, "thermal")
        hsi_dir, _ = self._sensor_dirs(site_id, "hsi")

        def load_records(source_dir: Path) -> list[tuple[float, dict, str]]:
            records = []
            for json_path in sorted(source_dir.glob("*.json")):
                try:
                    with json_path.open("r", encoding="utf-8") as handle:
                        raw = json.load(handle)
                    timestamp = raw.get("timestamp_utc")
                    if isinstance(timestamp, bool):
                        continue
                    timestamp = float(timestamp)
                    if not math.isfinite(timestamp):
                        continue
                except (json.JSONDecodeError, OSError, TypeError, ValueError, AttributeError):
                    continue
                record_id = str(raw.get("record_id") or json_path.stem)
                records.append((timestamp, raw, record_id))
            return sorted(records, key=lambda record: record[0])

        thermal_records = load_records(thermal_dir)
        hsi_records = load_records(hsi_dir)
        crs = site_cfg.get("crs_native", "EPSG:4326")
        tolerance_s = float(self.tolerance_s)
        fused_records = []
        hsi_index = 0

        # Consuming the earliest eligible HSI record gives one-to-one matches
        # while preserving the maximum number of pairs for sorted timestamps.
        for thermal_timestamp, thermal_raw, thermal_id in thermal_records:
            while (
                hsi_index < len(hsi_records)
                and hsi_records[hsi_index][0] < thermal_timestamp - tolerance_s
            ):
                hsi_index += 1
            if hsi_index >= len(hsi_records):
                break

            hsi_timestamp, hsi_raw, hsi_id = hsi_records[hsi_index]
            if hsi_timestamp > thermal_timestamp + tolerance_s:
                continue

            thermal = harmonize(thermal_raw, site_id, "thermal", crs)
            hsi = harmonize(hsi_raw, site_id, "hsi", crs)
            fused = {
                **hsi,
                **{
                    field: thermal[field]
                    for field in (
                        "temperature_c",
                        "thermal_min_c",
                        "thermal_max_c",
                        "thermal_avg_c",
                    )
                    if thermal[field] is not None
                },
                "sensor_type": "fused_thermal_hsi",
                "record_id": f"{site_id}_fused_{hsi_timestamp:.6f}",
                "source_records": {"thermal": thermal_id, "hsi": hsi_id},
            }
            fused_records.append(fused)
            hsi_index += 1

        archive_root = Path(
            self.config.get("fusion", {}).get("archive_dir", "data/fused_archive")
        )
        output_dir = archive_root / site_id
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / "fused_records.json"
        with output_file.open("w", encoding="utf-8") as handle:
            json.dump(fused_records, handle, sort_keys=True, indent=2)

        return {
            "site_id": site_id,
            "thermal_count": len(thermal_records),
            "hsi_count": len(hsi_records),
            "matched_count": len(fused_records),
            "unmatched_thermal_count": len(thermal_records) - len(fused_records),
            "unmatched_hsi_count": len(hsi_records) - len(fused_records),
            "output_dir": str(output_dir),
            "output_file": str(output_file),
        }

    def _try_fuse(self, site_id: str):
        t_buf = self._buf(self.thermal_buffer, site_id)
        h_buf = self._buf(self.hsi_buffer, site_id)
        if not t_buf or not h_buf:
            return
        t = t_buf[-1]
        h = h_buf[-1]
        if abs(t["timestamp_utc"] - h["timestamp_utc"]) <= self.tolerance_s:
            fused = {
                **h,
                **{
                    key: value
                    for key, value in t.items()
                    if key in (
                        "temperature_c",
                        "thermal_min_c",
                        "thermal_max_c",
                        "thermal_avg_c",
                    )
                },
            }
            fused["sensor_type"] = "fused_thermal_hsi"
            fused["record_id"] = f"{site_id}_fused_{fused['timestamp_utc']}"
            self._qa_and_store(site_id, fused)
            t_buf.pop()
            h_buf.pop()

    def _qa_and_store(self, site_id: str, fused: dict):
        history_df = pd.DataFrame(list(self.fused_buffer)) if self.fused_buffer else pd.DataFrame()
        required = ["timestamp_utc", "temperature_c", "hsi_serial_number", "crs"]
        report = run_qa_pipeline(
            fused, history_df, self.config, self._last_ts.get(site_id),
            required_fields=[f for f in required if f in fused], numeric_field="temperature_c"
        )
        self.qa_reports.append(report)
        self._last_ts[site_id] = fused["timestamp_utc"]

        if report["overall_pass"]:
            self.fused_buffer.append(fused)
        else:
            self.quarantine_buffer.append({"record": fused, "qa": report})

    def latest(self):
        return self.fused_buffer[-1] if self.fused_buffer else None

    def history(self, n: int = 100):
        return list(self.fused_buffer)[-n:]

    def qa_summary(self, n: int = 50):
        return list(self.qa_reports)[-n:]