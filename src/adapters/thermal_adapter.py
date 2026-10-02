import threading
import logging
import math
import requests
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class ThermalPoller(threading.Thread):
    def __init__(
        self,
        site_id: str,
        ip: str,
        port: int,
        poll_hz: float,
        callback,
        endpoint: str = "/api/spot",
        temperature_field: str = "spot_temp_f",
        timeout_s: float = 2.0,
    ):
        super().__init__(daemon=True)
        self.site_id = site_id
        self.base_url = f"http://{ip}:{port}"
        self.endpoint = "/" + endpoint.lstrip("/")
        self.temperature_field = temperature_field
        self.timeout_s = timeout_s
        self.interval = 1.0 / max(poll_hz, 0.1)
        self.callback = callback
        self._stop_event = threading.Event()
        self._offline = False
        self._failure_count = 0

    def _read_spot_temperature(self) -> dict | None:
        url = f"{self.base_url}{self.endpoint}"
        try:
            resp = requests.get(url, timeout=self.timeout_s)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                raise ValueError("response must be a JSON object")
            temperature = data.get(self.temperature_field)
            if temperature is None:
                raise ValueError(
                    f"response does not contain configured field "
                    f"{self.temperature_field!r}"
                )
            if isinstance(temperature, bool):
                raise ValueError("temperature value must be numeric")
            temperature = float(temperature)
            if not math.isfinite(temperature):
                raise ValueError("temperature value must be finite")
            if self._offline:
                logger.info("[ThermalPoller:%s] camera connection restored", self.site_id)
            self._offline = False
            self._failure_count = 0
            return {
                "temp_f": temperature,
                "timestamp_utc": datetime.now(timezone.utc).timestamp(),
            }
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code == 404:
                self._record_failure(
                    f"endpoint not found (HTTP 404) at {url}; camera responded, "
                    "check thermal.spot_endpoint against the camera API"
                )
            else:
                self._record_failure(f"HTTP request failed for {url}: {exc}")
            return None
        except requests.RequestException as exc:
            self._record_failure(f"camera request failed for {url}: {exc}")
            return None
        except (TypeError, ValueError) as exc:
            self._record_failure(f"invalid response from {url}: {exc}")
            return None

    def _record_failure(self, reason: str) -> None:
        self._failure_count += 1
        if not self._offline:
            logger.warning("[ThermalPoller:%s] %s", self.site_id, reason)
            self._offline = True
        elif self._failure_count == 10:
            logger.warning(
                "[ThermalPoller:%s] still failing after %d attempts: %s",
                self.site_id,
                self._failure_count,
                reason,
            )

    def run(self):
        while not self._stop_event.is_set():
            reading = self._read_spot_temperature()
            if reading:
                self.callback(self.site_id, reading)
            retry_interval = min(self.interval * (2 ** min(self._failure_count, 5)), 60.0)
            self._stop_event.wait(retry_interval)

    def stop(self):
        self._stop_event.set()