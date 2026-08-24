"""
Polls a FLIR AX8 thermal camera over its network (IP configured per site).
Replace `_read_spot_temperature` with the actual FLIR AX8 web/ONVIF call
for your firmware once confirmed (AX8 exposes spot data via its web UI /
Raymarine bridge; adjust endpoint/auth as needed).
"""
import threading
import time
import requests
from datetime import datetime, timezone


class ThermalPoller(threading.Thread):
    def __init__(self, site_id: str, ip: str, port: int, poll_hz: float, callback):
        super().__init__(daemon=True)
        self.site_id = site_id
        self.base_url = f"http://{ip}:{port}"
        self.interval = 1.0 / max(poll_hz, 0.1)
        self.callback = callback
        self._stop = threading.Event()

    def _read_spot_temperature(self) -> dict | None:
        try:
            # TODO: adjust to your AX8's real endpoint (ONVIF/CGI/Modbus bridge)
            resp = requests.get(f"{self.base_url}/api/spot", timeout=2)
            resp.raise_for_status()
            data = resp.json()
            return {
                "temp_f": data.get("spot_temp_f"),
                "timestamp_utc": datetime.now(timezone.utc).timestamp(),
            }
        except Exception as e:
            print(f"[ThermalPoller:{self.site_id}] read error: {e}")
            return None

    def run(self):
        while not self._stop.is_set():
            reading = self._read_spot_temperature()
            if reading:
                self.callback(self.site_id, reading)
            time.sleep(self.interval)

    def stop(self):
        self._stop.set()