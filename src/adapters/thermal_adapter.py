import threading
import logging
import math
import inspect
import requests
import struct
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
        protocol: str = "http",
        modbus_register_address: int = 1018,
        modbus_unit_id: int = 1,
    ):
        super().__init__(daemon=True)
        if protocol not in {"http", "modbus_tcp"}:
            raise ValueError(f"Unsupported thermal protocol: {protocol!r}")
        self.site_id = site_id
        self.ip = ip
        self.port = port
        self.base_url = f"http://{ip}:{port}"
        self.endpoint = "/" + endpoint.lstrip("/")
        self.temperature_field = temperature_field
        self.timeout_s = timeout_s
        self.protocol = protocol
        self.modbus_register_address = modbus_register_address
        self.modbus_unit_id = modbus_unit_id
        self.interval = 1.0 / max(poll_hz, 0.1)
        self.callback = callback
        self._stop_event = threading.Event()
        self._offline = False
        self._failure_count = 0

    def _read_spot_temperature(self) -> dict | None:
        if self.protocol == "modbus_tcp":
            return self._read_modbus_temperature()

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

    @staticmethod
    def _decode_modbus_float(registers: list[int]) -> float:
        if len(registers) != 2 or any(not 0 <= value <= 0xFFFF for value in registers):
            raise ValueError("temperature must be encoded in two 16-bit registers")
        raw = (registers[1] << 16) | registers[0]
        return struct.unpack(">f", struct.pack(">I", raw))[0]

    def _read_modbus_temperature(self) -> dict | None:
        from pymodbus.client import ModbusTcpClient
        from pymodbus.exceptions import ModbusException

        client = ModbusTcpClient(self.ip, port=self.port, timeout=self.timeout_s)
        try:
            if not client.connect():
                raise ConnectionError(f"could not connect to {self.ip}:{self.port}")

            read_registers = client.read_holding_registers
            parameters = inspect.signature(read_registers).parameters
            args = [self.modbus_register_address]
            kwargs = {}
            if "count" in parameters:
                kwargs["count"] = 8
            else:
                args.append(8)

            for unit_parameter in ("device_id", "slave", "unit"):
                if unit_parameter in parameters:
                    kwargs[unit_parameter] = self.modbus_unit_id
                    break

            response = read_registers(*args, **kwargs)
            if (
                response is None
                or not hasattr(response, "isError")
                or response.isError()
                or not hasattr(response, "registers")
            ):
                raise ValueError("camera returned a Modbus error response")
            registers = response.registers
            if len(registers) < 8:
                raise ValueError(
                    f"expected 8 temperature registers, received {len(registers)}"
                )

            temperatures = [
                self._decode_modbus_float(registers[index:index + 2])
                for index in range(0, 8, 2)
            ]
            if not all(math.isfinite(value) for value in temperatures):
                raise ValueError("camera returned a non-finite temperature")

            spot, box_min, box_max, box_avg = temperatures
            if not -10.0 <= spot <= 200.0:
                swapped = [
                    self._decode_modbus_float(registers[index:index + 2][::-1])
                    for index in range(0, 8, 2)
                ]
                if not all(math.isfinite(value) for value in swapped):
                    raise ValueError("camera returned a non-finite temperature")
                spot, box_min, box_max, box_avg = swapped
            if not -10.0 <= spot <= 200.0:
                raise ValueError(f"spot temperature is outside valid range: {spot}")

            if self._offline:
                logger.info("[ThermalPoller:%s] camera connection restored", self.site_id)
            self._offline = False
            self._failure_count = 0
            return {
                "thermal_temperature": spot,
                "box1_min_c": box_min,
                "box1_max_c": box_max,
                "box1_avg_c": box_avg,
                "timestamp_utc": datetime.now(timezone.utc).timestamp(),
            }
        except (ModbusException, OSError, TypeError, ValueError, struct.error) as exc:
            self._record_failure(f"Modbus request failed for {self.ip}:{self.port}: {exc}")
            return None
        finally:
            client.close()

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