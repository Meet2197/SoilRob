import os
import socket
import struct
import time
from enum import IntEnum
 
 
class BCodes(IntEnum):
    STOP_RGB_STREAM = 0
    START_RGB_STREAM = 1
    GET_SET_TIMEZONE = 2
    GET_SET_HSI_GAIN_EXPOSURE = 3
    SET_IP_ADDRESS = 4
    GET_SET_FPS = 6
    START_STOP_HSI_LINE = 7
    HSI_SCAN = 8
    MAKE_RGB_IMAGE = 9
    DOWNLOAD_DELETE_LATEST_DATA = 10
    GET_SERIAL_NUMBER = 12
    GET_VERSION_NUMBER = 13
    UPDATE_BULLET = 14
    GET_IMAGES_LIST = 20
    GET_IMAGES = 21
    DELETE_IMAGES = 22
  
class FILE_ID(IntEnum):
    HSI_IMAGE = 1
    HDR_FILE = 2
    FULLSIZE_RGB = 4
    PNG_RGB = 8 
 
class BlackBullet:
    """
    Example:
        cam = BlackBullet(ip="192.168.7.1")
        print(cam.get_serial_number())
        cam.set_gain_exposure(gain=1.0, exposure_us=5000)
        cam.take_hsi_image(description="field_test_01")
        time.sleep(10)                      # give it time to scan + save
        cam.download_latest(save_path=".")
    """
 
    def __init__(self, ip="192.168.7.1", port=7892):
        self._TCP_IP = ip
        self._TCP_PORT = port
 
    def _start_connection(self, timeout=5):
        conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        conn.settimeout(timeout)
        try:
            conn.connect((self._TCP_IP, self._TCP_PORT))
            return conn
        except Exception as e:
            print(f"Could not connect to camera: {e}")
            return None
 
    def _send_command(self, b_code, v1=0, v2=0, sensor=1,
                       set_get=0, data="", timeout=5):
        conn = self._start_connection(timeout)
        if conn is None:
            return None
        message = struct.pack('<bbhIIi', sensor, set_get, b_code,
                               v1, v2, int(time.time()))
        conn.send(message)
        if data:
            conn.send(data.encode())
        return conn
 
    def _receive_exact(self, sock, size):
        """Receive exactly 'size' bytes from the socket."""
        data = b''
        remaining = size
        while remaining > 0:
            chunk = sock.recv(remaining)
            if not chunk:
                raise RuntimeError("Socket connection broken")
            data += chunk
            remaining -= len(chunk)
        return data
 
    # ---------- Simple getters ----------
    def get_serial_number(self):
        conn = self._send_command(BCodes.GET_SERIAL_NUMBER)
        if conn is None:
            return None
        size = struct.unpack('<i', conn.recv(4))[0]
        value = conn.recv(size).decode()
        conn.close()
        return value
 
    def get_version(self):
        conn = self._send_command(BCodes.GET_VERSION_NUMBER)
        if conn is None:
            return None
        size = struct.unpack('<i', conn.recv(4))[0]
        value = conn.recv(size).decode()
        conn.close()
        return value
 
    # ---------- Settings ----------
    def set_gain_exposure(self, gain, exposure_us):
        """Set gain (1.0-15.5) and exposure time in microseconds
        (100-5000) for snapshot mode."""
        gain_int = int(round(gain, 1) * 10)
        conn = self._send_command(BCodes.GET_SET_HSI_GAIN_EXPOSURE,
                                   v1=gain_int, v2=int(exposure_us),
                                   set_get=0)
        if conn:
            conn.close()
 
    def get_gain_exposure(self):
        conn = self._send_command(BCodes.GET_SET_HSI_GAIN_EXPOSURE,
                                   set_get=1)
        if conn is None:
            return None, None
        ret = conn.recv(16)
        _, _, _, gain, exposure, _ = struct.unpack('<bbhIIi', ret)
        conn.close()
        return gain / 10.0, exposure
 
    def set_timezone(self, tz_name="Europe/Berlin"):
        conn = self._send_command(BCodes.GET_SET_TIMEZONE,
                                   v1=len(tz_name), set_get=0,
                                   data=tz_name)
        if conn:
            conn.close()
 
    # ---------- Capture ----------
    def take_hsi_image(self, description=""):
        """Trigger a snapshot HSI image capture (camera stays still)."""
        conn = self._send_command(BCodes.HSI_SCAN,
                                   v1=len(description), set_get=0)
        if conn:
            if description:
                conn.send(description.encode())
            conn.close()
            print(f"HSI image triggered at {time.time()}")
 
    def take_rgb_image(self, description=""):
        """Trigger an RGB image capture."""
        conn = self._send_command(BCodes.MAKE_RGB_IMAGE,
                                   v1=len(description), set_get=0)
        if conn:
            if description:
                conn.send(description.encode())
            conn.close()
 
    # ---------- Download ----------
    def download_latest(self, save_path="./"):
        """Download the most recently captured image files
        (.img, .hdr, _FS.tif, .png)."""
        files = (FILE_ID.HSI_IMAGE | FILE_ID.HDR_FILE |
                 FILE_ID.FULLSIZE_RGB | FILE_ID.PNG_RGB)
        conn = self._send_command(BCodes.DOWNLOAD_DELETE_LATEST_DATA,
                                   set_get=1, v1=files)
        if conn is None:
            return
 
        mess = conn.recv(16)
        orig_filename = conn.recv(
            struct.unpack('<bbhIIi', mess)[3]).decode()
        print(f"Downloading: {orig_filename}")
 
        while True:
            _, _, _, file_type, file_size, _ = struct.unpack(
                '<bbhIIi', conn.recv(16))
            if file_type == 0:
                break
            file_data = self._receive_exact(conn, file_size)
            tmp_filename = os.path.join(save_path, orig_filename)
            if file_type == FILE_ID.HSI_IMAGE:
                tmp_filename += "_raw.img"
            elif file_type == FILE_ID.HDR_FILE:
                tmp_filename += "_raw.hdr"
            elif file_type == FILE_ID.FULLSIZE_RGB:
                tmp_filename += "_FS.tif"
            elif file_type == FILE_ID.PNG_RGB:
                tmp_filename += ".png"
            with open(tmp_filename, "wb") as f:
                f.write(file_data)
            print(f"  Saved: {tmp_filename}")
        conn.close()