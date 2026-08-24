import threading
from collections import deque
import pandas as pd
from src.qa.qa_protocol import run_qa_pipeline
from src.semantic.alignment import harmonize


class FusionEngine:
    def __init__(self, config: dict):
        self.config = config
        tol = config["fusion"]["time_tolerance_s"]
        bufsize = config["fusion"]["buffer_size"]
        self.tolerance_s = tol
        self.thermal_buffer: dict[str, deque] = {}
        self.lidar_buffer: dict[str, deque] = {}
        self.fused_buffer: deque = deque(maxlen=bufsize)
        self.quarantine_buffer: deque = deque(maxlen=bufsize)
        self.qa_reports: deque = deque(maxlen=bufsize)
        self._last_ts: dict[str, float] = {}
        self.lock = threading.Lock()

    def _buf(self, store: dict, site_id: str) -> deque:
        if site_id not in store:
            store[site_id] = deque(maxlen=self.config["fusion"]["buffer_size"])
        return store[site_id]

    def add_thermal(self, site_id: str, raw: dict, crs: str = "EPSG:4326"):
        rec = harmonize(raw, site_id, "thermal", crs)
        with self.lock:
            self._buf(self.thermal_buffer, site_id).append(rec)
            self._try_fuse(site_id)

    def add_lidar(self, site_id: str, raw: dict, crs: str = "EPSG:4326"):
        rec = harmonize(raw, site_id, "lidar", crs)
        with self.lock:
            self._buf(self.lidar_buffer, site_id).append(rec)
            self._try_fuse(site_id)

    def _try_fuse(self, site_id: str):
        t_buf = self._buf(self.thermal_buffer, site_id)
        l_buf = self._buf(self.lidar_buffer, site_id)
        if not t_buf or not l_buf:
            return
        t = t_buf[-1]
        l = l_buf[-1]
        if abs(t["timestamp_utc"] - l["timestamp_utc"]) <= self.tolerance_s:
            fused = {**l, **{k: v for k, v in t.items() if k in ("temperature_c",)}}
            fused["sensor_type"] = "fused_thermal_lidar"
            fused["record_id"] = f"{site_id}_fused_{fused['timestamp_utc']}"
            self._qa_and_store(site_id, fused)
            t_buf.pop()
            l_buf.pop()

    def _qa_and_store(self, site_id: str, fused: dict):
        history_df = pd.DataFrame(list(self.fused_buffer)) if self.fused_buffer else pd.DataFrame()
        required = ["timestamp_utc", "temperature_c", "range_m", "crs"]
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