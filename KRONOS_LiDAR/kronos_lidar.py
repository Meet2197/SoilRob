""" 
    Linux + USB/native CAN adapter (SocketCAN), most common on a robot PC:
        sudo ip link set can0 up type can bitrate 250000
        KronosLidar(channel="can0", interface="socketcan")
 
    PEAK-System PCAN-USB dongle (Windows or Linux):
        KronosLidar(channel="PCAN_USBBUS1", interface="pcan", bitrate=250000)
 
    Kvaser USB adapter:
        KronosLidar(channel="0", interface="kvaser", bitrate=250000)
 
    Serial/slcan adapter (e.g. CANtact, USBtin):
        KronosLidar(channel="/dev/ttyUSB0", interface="slcan", bitrate=250000)
 
    No hardware yet / just testing your code:
        KronosLidar(channel="test", interface="virtual")
"""
 
import struct
import time
from enum import IntEnum
 
import can
 
CAN_ID_CONTROL = 0x123     # we -> sensor
CAN_ID_STATUS = 0x124      # sensor -> us, every ~200 ms
CAN_ID_ROUGHNESS = 0x125   # sensor -> us, every ~30 ms
 
 
class Mode(IntEnum):
    """Values written into the Control frame (byte 0) to command the sensor."""
    IDLE = 0x01
    MEASURE = 0x02
    STOP = 0x04
 
 
class SensorState(IntEnum):
    """Values read back in the Status frame (byte 0)."""
    BOOTING = 0x00
    IDLE = 0x01
    MEASURING = 0x02
    ERROR = 0x03
    STOPPING = 0x04
 
# Bit tables from the "Wertetabelle" columns in the CAN-Messages slide
ERROR_BITS = {
    0: "no connection",
    1: "connection lost",
    2: "internal error",
    3: "device error",
    4: "lens contamination",
    5: "low temperature",
    6: "high temperature",
    7: "overload",
}
 
WARNING_BITS = {
    0: "device warning",
    1: "lens contamination",
    2: "low temperature",
    3: "high temperature",
    4: "device overload",
}
 
 
def _decode_flags(value, bit_table):
    return [text for bit, text in bit_table.items() if value & (1 << bit)]
 
 
class KronosLidar:
    """
    Thin wrapper around a python-can Bus that speaks the KRONOS scanner's
    Control / Status / Roughness frames.
 
    Example:
        lidar = KronosLidar(channel="can0", interface="socketcan")
        lidar.start_measuring(opening_angle=90)
 
        reading = lidar.wait_for_roughness(timeout=1.0)
        print(reading)  # {'roughness_1': 12.34, 'roughness_2': ..., ...}
 
        lidar.stop()
        lidar.close()
    """
 
    def __init__(self, channel="can0", interface="socketcan", bitrate=250000):
        self.bus = can.interface.Bus(channel=channel, interface=interface,
                                      bitrate=bitrate)
        self.latest_status = None
        self.latest_roughness = None
 
    # ---------- Commands (we send these) ----------
    def send_control(self, mode, opening_angle=0):
        """Send a Control frame: desired mode + opening angle (0-255 deg)."""
        if not 0 <= opening_angle <= 255:
            raise ValueError("opening_angle must be 0-255")
        data = struct.pack("<BB", int(mode), opening_angle)
        msg = can.Message(arbitration_id=CAN_ID_CONTROL, data=data,
                           is_extended_id=False)
        self.bus.send(msg)
 
    def start_measuring(self, opening_angle=120):
        self.send_control(Mode.MEASURE, opening_angle)
 
    def go_idle(self):
        self.send_control(Mode.IDLE)
 
    def stop(self):
        self.send_control(Mode.STOP)
 
    # ---------- Readings (the sensor sends these on its own) ----------
    def read_next(self, timeout=1.0):
        """
        Block until the next Status or Roughness frame arrives (or timeout).
        Returns ("status", dict) / ("roughness", dict), or None if nothing
        relevant showed up before the timeout.
        """
        msg = self.bus.recv(timeout=timeout)
        if msg is None:
            return None
        if msg.arbitration_id == CAN_ID_STATUS:
            status = self._parse_status(msg.data)
            self.latest_status = status
            return "status", status
        if msg.arbitration_id == CAN_ID_ROUGHNESS:
            roughness = self._parse_roughness(msg.data)
            self.latest_roughness = roughness
            return "roughness", roughness
        return None
 
    def wait_for_status(self, timeout=2.0):
        """Poll until a Status frame arrives or timeout elapses."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            result = self.read_next(timeout=max(0, deadline - time.time()))
            if result and result[0] == "status":
                return result[1]
        return None
 
    def wait_for_roughness(self, timeout=2.0):
        """Poll until a Roughness frame arrives or timeout elapses."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            result = self.read_next(timeout=max(0, deadline - time.time()))
            if result and result[0] == "roughness":
                return result[1]
        return None
 
    @staticmethod
    def _parse_status(data):
        mode, angle, error_code, warning_code = struct.unpack("<BBHH", bytes(data[:6]))
        try:
            mode = SensorState(mode)
        except ValueError:
            pass  # unknown value, leave as raw int
        return {
            "mode": mode,
            "opening_angle_deg": angle,
            "error_code": error_code,
            "error_flags": _decode_flags(error_code, ERROR_BITS),
            "warning_code": warning_code,
            "warning_flags": _decode_flags(warning_code, WARNING_BITS),
        }
 
    @staticmethod
    def _parse_roughness(data):
        r1, r2, r3 = struct.unpack("<HHH", bytes(data[:6]))
        return {
            "roughness_1": r1 / 100.0,
            "roughness_2": r2 / 100.0,
            "roughness_3": r3 / 100.0,
        }
 
    def close(self):
        self.bus.shutdown()
 
 
if __name__ == "__main__":
    # Quick manual smoke test against a real bus. Change interface/channel
    # to match your hardware (see the module docstring above).
    lidar = KronosLidar(channel="can0", interface="socketcan")
    lidar.start_measuring(opening_angle=100)
    print("Status:", lidar.wait_for_status(timeout=2.0))
    print("Roughness:", lidar.wait_for_roughness(timeout=2.0))
    lidar.stop()
    lidar.close()