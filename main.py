import yaml
from pathlib import Path
import uvicorn

from src.fusion.fusion_engine import FusionEngine
from src.adapters.thermal_adapter import ThermalPoller
from src.adapters.hsi_adapter import HSIPoller
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

        h_cfg = site_cfg["hsi"]
        h_poller = HSIPoller(
            site_id, h_cfg["ip"], h_cfg["port"], h_cfg["gain"], h_cfg["exposure_us"],
            callback=lambda sid, raw, c=crs: engine.add_hsi(sid, raw, c),
        )
        h_poller.start()
        pollers.append(h_poller)

    print(f"SoilRob Fusion API starting on {config['api']['host']}:{config['api']['port']}")
    uvicorn.run(unified_api.app, host=config["api"]["host"], port=config["api"]["port"])


if __name__ == "__main__":
    main()