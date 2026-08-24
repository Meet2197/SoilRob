import yaml
from pathlib import Path
import uvicorn

from src.fusion.fusion_engine import FusionEngine
from src.adapters.thermal_adapter import ThermalPoller
from src.adapters.lidar_adapter import LidarPoller
import src.api.unified_api as unified_api

CONFIG_PATH = Path(__file__).parent / "config" / "sites.yaml"


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def main():
    config = load_config()
    engine = FusionEngine(config)
    unified_api.engine = engine  # inject dependency

    pollers = []
    for site_id, site_cfg in config["sites"].items():
        crs = site_cfg["crs_native"]

        t_cfg = site_cfg["thermal"]
        t_poller = ThermalPoller(
            site_id, t_cfg["ip"], t_cfg["port"], t_cfg["poll_hz"],
            callback=lambda sid, raw, c=crs: engine.add_thermal(sid, raw, c),
        )
        t_poller.start()
        pollers.append(t_poller)

        l_cfg = site_cfg["lidar"]
        l_poller = LidarPoller(
            site_id, l_cfg["can_channel"], l_cfg["bitrate"], l_cfg["status_id"],
            callback=lambda sid, raw, c=crs: engine.add_lidar(sid, raw, c),
        )
        l_poller.start()
        pollers.append(l_poller)

    print(f"SoilRob Fusion API starting on {config['api']['host']}:{config['api']['port']}")
    uvicorn.run(unified_api.app, host=config["api"]["host"], port=config["api"]["port"])


if __name__ == "__main__":
    main()