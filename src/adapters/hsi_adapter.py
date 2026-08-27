"""
Polls / triggers a HAIP BlackBullet V2 camera over its TCP/IP API
(default port 7892). Wraps the BlackBullet class pattern from the
HAIP API guide (16-byte command packets).
"""
import threading
import time
import struct
import socket
from datetime import datetime, timezone


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
        self._stop = threading.Event()

    def _connect(self, timeout=5):
        conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        conn.settimeout(timeout)
        conn.connect((self.ip, self.port))
        return conn

    def _get_serial_number(self) -> str | None:
        try:
            conn = self._connect()
            message = struct.pack('<bbhIIi', 1, 0, 12, 0, 0, int(time.time()))
            conn.send(message)
            size = struct.unpack('<i', conn.recv(4))[0]
            serial = conn.recv(size).decode()
            conn.close()
            return serial
        except Exception as e:
            print(f"[HSIPoller:{self.site_id}] serial read error: {e}")
            return None

    def _set_gain_exposure(self) -> bool:
        try:
            conn = self._connect()
            gain_int = int(round(self.gain, 1) * 10)
            message = struct.pack('<bbhIIi', 1, 0, 3, gain_int, int(self.exposure_us), int(time.time()))
            conn.send(message)
            conn.close()
            return True
        except Exception as e:
            print(f"[HSIPoller:{self.site_id}] set gain/exposure error: {e}")
            return False

    def _trigger_hsi_image(self, description: str = "") -> bool:
        try:
            conn = self._connect()
            message = struct.pack('<bbhIIi', 1, 0, 8, len(description), 0, int(time.time()))
            conn.send(message)
            if description:
                conn.send(description.encode())
            conn.close()
            return True
        except Exception as e:
            print(f"[HSIPoller:{self.site_id}] trigger HSI error: {e}")
            return False

    def run(self):
        settings_applied = self._set_gain_exposure()
        serial = self._get_serial_number()
        if serial is None:
            print(f"[HSIPoller:{self.site_id}] unavailable; serial number could not be read")
        else:
            print(
                f"[HSIPoller:{self.site_id}] connected, serial={serial}"
                f" (settings={'applied' if settings_applied else 'not applied'})"
            )

        while not self._stop.is_set():
            description = f"{self.site_id}_{int(time.time())}"
            if self._trigger_hsi_image(description):
                reading = {
                    "gain": self.gain,
                    "exposure_us": self.exposure_us,
                    "serial_number": serial,
                    "image_path": description,
                    "timestamp_utc": datetime.now(timezone.utc).timestamp(),
                }
                self.callback(self.site_id, reading)
            time.sleep(self.interval_s)

    def stop(self):
        self._stop.set()