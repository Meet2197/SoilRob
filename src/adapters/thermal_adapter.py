import threading
import logging
import requests
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class ThermalPoller(threading.Thread):
    def __init__(self, site_id: str, ip: str, port: int, poll_hz: float, callback):
        super().__init__(daemon=True)
        self.site_id = site_id
        self.base_url = f"http://{ip}:{port}"
        self.interval = 1.0 / max(poll_hz, 0.1)
        self.callback = callback
        self._stop = threading.Event()
        self._offline = False
        self._failure_count = 0

    def _read_spot_temperature(self) -> dict | None:
        try:
            resp = requests.get(f"{self.base_url}/api/spot", timeout=2)
            resp.raise_for_status()
            data = resp.json()
            temperature = data.get("spot_temp_f")
            if temperature is None:
                raise ValueError("FLIR response does not contain spot_temp_f")
            if self._offline:
                logger.info("[ThermalPoller:%s] camera connection restored", self.site_id)
            self._offline = False
            self._failure_count = 0
            return {
                "temp_f": temperature,
                "timestamp_utc": datetime.now(timezone.utc).timestamp(),
            }
        except (requests.RequestException, ValueError) as exc:
            self._failure_count += 1
            if not self._offline:
                logger.warning("[ThermalPoller:%s] camera offline: %s", self.site_id, exc)
                self._offline = True
            elif self._failure_count == 10:
                logger.warning("[ThermalPoller:%s] still offline after %d attempts", self.site_id, self._failure_count)
            return None

    def run(self):
        while not self._stop.is_set():
            reading = self._read_spot_temperature()
            if reading:
                self.callback(self.site_id, reading)
            retry_interval = min(self.interval * (2 ** min(self._failure_count, 5)), 60.0)
            self._stop.wait(retry_interval)

    def stop(self):
        self._stop.set()