"""
Polls / triggers a HAIP BlackBullet V2 camera over its TCP/IP API
(default port 7892). Wraps the BlackBullet class pattern from the
HAIP API guide (16-byte command packets).
"""
import threading
import time
import struct
import socket
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class HSIPoller(threading.Thread):
    def __init__(self, site_id: str, ip: str, port: int, gain: float,
                 exposure_us: int, callback, interval_s: float = 10.0):
        super().__init__(daemon=True)
        self.site_id = site_id
        self.ip = ip
        self.port = port
        self.gain = gain
        self.exposure_us = exposure_us
        self.callback = callback
        self.interval_s = interval_s
        self._stop_event = threading.Event()
        self._offline = False
        self._failure_count = 0

    def _connect(self, timeout=2):
        conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        conn.settimeout(timeout)
        conn.connect((self.ip, self.port))
        return conn

    @staticmethod
    def _recv_exact(conn, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = conn.recv(size - len(data))
            if not chunk:
                raise ConnectionError("HSI device closed the connection")
            data.extend(chunk)
        return bytes(data)

    def _get_serial_number(self) -> str | None:
        conn = None
        try:
            conn = self._connect()
            message = struct.pack('<bbhIIi', 1, 0, 12, 0, 0, int(time.time()))
            conn.sendall(message)
            size = struct.unpack('<i', self._recv_exact(conn, 4))[0]
            if size <= 0 or size > 4096:
                raise ValueError(f"invalid serial response size: {size}")
            serial = self._recv_exact(conn, size).decode().strip()
            return serial
        except (OSError, ValueError, UnicodeDecodeError):
            return None
        finally:
            if conn is not None:
                conn.close()

    def _set_gain_exposure(self) -> bool:
        conn = None
        try:
            conn = self._connect()
            gain_int = int(round(self.gain, 1) * 10)
            message = struct.pack('<bbhIIi', 1, 0, 3, gain_int, int(self.exposure_us), int(time.time()))
            conn.sendall(message)
            return True
        except (OSError, ValueError):
            return False
        finally:
            if conn is not None:
                conn.close()

    @staticmethod
    def _is_successful_ack_packet(packet: bytes | None) -> bool:
        if not isinstance(packet, (bytes, bytearray)):
            return False

        data = bytes(packet)
        if len(data) < 4:
            return False

        try:
            declared_length = struct.unpack('<i', data[:4])[0]
        except struct.error:
            return False

        if declared_length > 0 and len(data) >= 4 + declared_length:
            data = data[4:4 + declared_length]

        if len(data) < 16:
            return False

        try:
            sensor, getset, b_code, value1, value2, _ = struct.unpack('<bbhIIi', data[:16])
        except struct.error:
            return False

        return sensor in (0, 1) and getset in (0, 1) and b_code in (0, 8)

    def _read_trigger_ack(self, conn: socket.socket, timeout_s: float = 2.0) -> bytes | None:
        try:
            conn.settimeout(timeout_s)
            header = self._recv_exact(conn, 4)
            declared_length = struct.unpack('<i', header)[0]
            if declared_length <= 0 or declared_length > 4096:
                return None
            return self._recv_exact(conn, declared_length)
        except (ConnectionError, OSError, socket.timeout, struct.error, ValueError):
            return None

    def _trigger_hsi_image(self, description: str = "") -> bool:
        conn = None
        try:
            conn = self._connect()
            message = struct.pack('<bbhIIi', 1, 0, 8, len(description), 0, int(time.time()))
            conn.sendall(message)
            if description:
                conn.sendall(description.encode())
            ack = self._read_trigger_ack(conn)
            return self._is_successful_ack_packet(ack)
        except (OSError, ValueError):
            return False
        finally:
            if conn is not None:
                conn.close()

    def run(self):
        settings_applied = self._set_gain_exposure()
        serial = self._get_serial_number()
        if serial is None:
            self._mark_offline("serial number could not be read")
        else:
            self._mark_online()
            logger.info(
                f"[HSIPoller:{self.site_id}] connected, serial={serial}"
                f" (settings={'applied' if settings_applied else 'not applied'})"
            )

        while not self._stop_event.is_set():
            description = f"{self.site_id}_{int(time.time())}"
            if serial is None:
                serial = self._get_serial_number()
                if serial is not None:
                    logger.info("[HSIPoller:%s] serial number recovered: %s", self.site_id, serial)
            if self._trigger_hsi_image(description):
                self._mark_online()
                reading = {
                    "gain": self.gain,
                    "exposure_us": self.exposure_us,
                    "serial_number": serial,
                    "image_path": description,
                    "timestamp_utc": datetime.now(timezone.utc).timestamp(),
                }
                self.callback(self.site_id, reading)
            else:
                self._mark_offline("trigger request timed out or was rejected")
            retry_interval = min(self.interval_s * (2 ** min(self._failure_count, 5)), 60.0)
            self._stop_event.wait(retry_interval)

    def _mark_offline(self, reason: str) -> None:
        self._failure_count += 1
        if not self._offline:
            logger.warning("[HSIPoller:%s] camera offline: %s", self.site_id, reason)
            self._offline = True
        elif self._failure_count == 10:
            logger.warning("[HSIPoller:%s] still offline after %d attempts", self.site_id, self._failure_count)

    def _mark_online(self) -> None:
        if self._offline:
            logger.info("[HSIPoller:%s] camera connection restored", self.site_id)
        self._offline = False
        self._failure_count = 0

    def stop(self):
        self._stop_event.set()