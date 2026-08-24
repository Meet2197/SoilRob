"""
Reads LiDAR status frames over CAN (250 kBit, Intel/little-endian format)
per the datasheet:
  0x124 Status (DLC 6): Modus[0], Oeffnungswinkel[1], Fehlercode[2-3], Warnungscode[4-5]
"""
import threading
import struct
from datetime import datetime, timezone

try:
    import can
except ImportError:
    can = None  # allows import without hardware present, for testing


class LidarPoller(threading.Thread):
    def __init__(self, site_id: str, can_channel: str, bitrate: int, status_id: int, callback):
        super().__init__(daemon=True)
        self.site_id = site_id
        self.can_channel = can_channel
        self.bitrate = bitrate
        self.status_id = status_id
        self.callback = callback
        self._stop = threading.Event()

    def _decode_status(self, data: bytes) -> dict:
        modus = data[0]
        open_angle = data[1]
        error_code = struct.unpack_from("<H", data, 2)[0]
        warning_code = struct.unpack_from("<H", data, 4)[0]
        return {
            "Modus": modus,
            "Oeffnungswinkel": open_angle,
            "Fehlercode_Sensor": error_code,
            "Warnungscode_Sensor": warning_code,
            "timestamp_utc": datetime.now(timezone.utc).timestamp(),
        }

    def run(self):
        if can is None:
            print(f"[LidarPoller:{self.site_id}] python-can not installed - skipping")
            return
        try:
            bus = can.interface.Bus(channel=self.can_channel, bustype="socketcan", bitrate=self.bitrate)
        except Exception as e:
            print(f"[LidarPoller:{self.site_id}] CAN bus open failed: {e}")
            return

        while not self._stop.is_set():
            msg = bus.recv(timeout=1.0)
            if msg and msg.arbitration_id == self.status_id:
                reading = self._decode_status(msg.data)
                self.callback(self.site_id, reading)

    def stop(self):
        self._stop.set()