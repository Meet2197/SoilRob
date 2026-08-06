import csv
import time

from blackbullet_camera import BlackBullet
from kronos_lidar import KronosLidar

# ---------------- CONFIG ----------------
BLACKBULLET_IP = "192.168.7.1"      # default camera IP, see manual 6.1
CAN_CHANNEL = "can0"                # SocketCAN device name on Linux
CAN_INTERFACE = "socketcan"         # "pcan" / "kvaser" / "slcan" for other adapters
CAPTURE_INTERVAL_S = 5
NUM_CAPTURES = 20
LOG_FILE = "capture_log.csv"
LIDAR_OPENING_ANGLE = 120           # degrees, 60-120 per the mounting spec
# -----------------------------------------

def main():
    print("Connecting to BlackBullet V2...")
    cam = BlackBullet(ip=BLACKBULLET_IP)
    print("  serial:", cam.get_serial_number())
    print("  version:", cam.get_version())
    cam.set_timezone("Europe/Berlin")
    cam.set_gain_exposure(gain=1.0, exposure_us=5000)

    print("Connecting to KRONOS lidar...")
    lidar = KronosLidar(channel=CAN_CHANNEL, interface=CAN_INTERFACE)
    lidar.start_measuring(opening_angle=LIDAR_OPENING_ANGLE)
    startup = lidar.wait_for_status(timeout=3.0)
    print("  status:", startup)

    with open(LOG_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "image_id", "unix_timestamp", "iso_time",
            "roughness_1", "roughness_2", "roughness_3",
            "lidar_mode", "lidar_error_flags", "lidar_warning_flags",
        ])

        for i in range(NUM_CAPTURES):
            image_id = f"soilrob_{i:04d}"
            timestamp = time.time()
            iso = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))

            # 1) trigger the hyperspectral snapshot (camera saves it onboard)
            cam.take_hsi_image(description=image_id)

            # 2) grab the roughness + status reading closest to this moment
            roughness = lidar.wait_for_roughness(timeout=1.0) or {}
            status = lidar.latest_status or {}

            writer.writerow([
                image_id, timestamp, iso,
                roughness.get("roughness_1"),
                roughness.get("roughness_2"),
                roughness.get("roughness_3"),
                getattr(status.get("mode"), "name", status.get("mode")),
                status.get("error_flags"),
                status.get("warning_flags"),
            ])
            print(f"[{iso}] {image_id}  roughness={roughness}")

            time.sleep(CAPTURE_INTERVAL_S)

    lidar.stop()
    lidar.close()

    print("\nDone. Log written to", LOG_FILE)
    print("Now download the images, either one at a time with")
    print("  cam.download_latest(save_path='.')")
    print("right after each take_hsi_image() call, or in bulk afterwards")
    print("over FTP (user: ftp_haip / pass: haip).")


if __name__ == "__main__":
    main()