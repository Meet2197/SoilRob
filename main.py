from pathlib import Path
import logging
import signal
import sys
import uvicorn
import yaml

from src.fusion.fusion_engine import FusionEngine
from src.adapters.thermal_adapter import ThermalPoller
from src.adapters.hsi_adapter import HSIPoller
import src.api.unified_api as unified_api

# ============================================================
# Paths
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config" / "sites.yaml"


# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("SoilRob")


# ============================================================
# Configuration
# ============================================================

def load_config() -> dict:
    """Load and validate the SoilRob configuration."""

    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Configuration file not found: {CONFIG_PATH}"
        )

    logger.info("Loading configuration from %s", CONFIG_PATH)

    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as file:
            config = yaml.safe_load(file)
    except yaml.YAMLError as exc:
        raise RuntimeError(
            f"Invalid YAML configuration: {exc}"
        ) from exc

    if not isinstance(config, dict):
        raise ValueError("Configuration must contain a YAML mapping.")

    required_sections = ["sites", "fusion", "api"]

    for section in required_sections:
        if section not in config:
            raise ValueError(
                f"Missing required configuration section: '{section}'"
            )

    return config


# ============================================================
# Poller management
# ============================================================

def start_pollers(config: dict, engine: FusionEngine) -> list:
    """Create and start all configured sensor pollers."""

    pollers = []

    for site_id, site_cfg in config["sites"].items():

        logger.info("Initializing site: %s", site_id)

        # ----------------------------------------------------
        # Native CRS
        # ----------------------------------------------------

        crs = site_cfg.get("crs_native")

        if not crs:
            logger.warning(
                "[%s] No native CRS configured.",
                site_id,
            )

        # ----------------------------------------------------
        # Thermal
        # ----------------------------------------------------

        thermal_cfg = site_cfg.get("thermal")

        if thermal_cfg:
            if not thermal_cfg.get("acquisition_enabled", True):
                logger.info("[%s] Thermal acquisition disabled.", site_id)
                thermal_cfg = None
        if thermal_cfg:
            poll_hz = thermal_cfg.get("poll_hz")
            if poll_hz is None:
                acquisition_interval_s = thermal_cfg.get(
                    "acquisition_interval_s",
                    1.0,
                )
                poll_hz = 1.0 / acquisition_interval_s

            logger.info(
                "[%s] Starting thermal poller at %s:%s",
                site_id,
                thermal_cfg["ip"],
                thermal_cfg["port"],
            )

            thermal_poller = ThermalPoller(
                site_id,
                thermal_cfg["ip"],
                thermal_cfg["port"],
                poll_hz,
                callback=lambda sid, raw, c=crs:
                    engine.add_thermal(sid, raw, c),
            )

            thermal_poller.start()
            pollers.append(thermal_poller)

            logger.info(
                "[%s] Thermal poller started.",
                site_id,
            )

        else:
            logger.warning(
                "[%s] No thermal configuration found.",
                site_id,
            )

        # ----------------------------------------------------
        # HSI
        # ----------------------------------------------------

        hsi_cfg = site_cfg.get("hsi")

        if hsi_cfg:
            if not hsi_cfg.get("acquisition_enabled", True):
                logger.info("[%s] HSI acquisition disabled.", site_id)
                hsi_cfg = None
        if hsi_cfg:
            logger.info(
                "[%s] Starting HSI poller at %s:%s",
                site_id,
                hsi_cfg["ip"],
                hsi_cfg["port"],
            )

            hsi_poller = HSIPoller(
                site_id,
                hsi_cfg["ip"],
                hsi_cfg["port"],
                hsi_cfg["gain"],
                hsi_cfg["exposure_us"],
                callback=lambda sid, raw, c=crs:
                    engine.add_hsi(sid, raw, c),
                interval_s=hsi_cfg.get("acquisition_interval_s", 10.0),
            )

            hsi_poller.start()
            pollers.append(hsi_poller)

            logger.info(
                "[%s] HSI poller started.",
                site_id,
            )

        else:
            logger.warning(
                "[%s] No HSI configuration found.",
                site_id,
            )

    return pollers


def stop_pollers(pollers: list) -> None:
    """Stop all pollers that provide a stop() method."""

    logger.info("Stopping sensor pollers...")

    for poller in pollers:
        try:
            stop = getattr(poller, "stop", None)

            if callable(stop):
                stop()
                logger.info(
                    "Stopped %s",
                    type(poller).__name__,
                )

        except Exception:
            logger.exception(
                "Error while stopping %s",
                type(poller).__name__,
            )


# ============================================================
# Application
# ============================================================

def main() -> None:
    """Start the complete SoilRob platform."""

    logger.info("=" * 60)
    logger.info("Starting SoilRob Multi-Sensor Fusion Platform")
    logger.info("=" * 60)

    pollers = []

    try:
        # ----------------------------------------------------
        # Load configuration
        # ----------------------------------------------------

        config = load_config()

        # ----------------------------------------------------
        # Initialize Fusion Engine
        # ----------------------------------------------------

        logger.info("Initializing FusionEngine...")

        engine = FusionEngine(config)

        # Inject engine into FastAPI module
        unified_api.engine = engine

        logger.info("FusionEngine initialized.")

        # ----------------------------------------------------
        # Start sensor pollers
        # ----------------------------------------------------

        pollers = start_pollers(
            config,
            engine,
        )

        logger.info(
            "Started %d sensor poller(s).",
            len(pollers),
        )

        # ----------------------------------------------------
        # API configuration
        # ----------------------------------------------------

        api_cfg = config["api"]

        host = api_cfg.get("host", "127.0.0.1")
        port = int(api_cfg.get("port", 8000))

        logger.info(
            "SoilRob Fusion API starting on %s:%d",
            host,
            port,
        )

        logger.info(
            "API documentation: http://localhost:%d/docs",
            port,
        )

        logger.info("=" * 60)

        # ----------------------------------------------------
        # Start Uvicorn
        # ----------------------------------------------------

        uvicorn.run(
            unified_api.app,
            host=host,
            port=port,
            log_level="info",
        )

    except KeyboardInterrupt:
        logger.info("Shutdown requested by user.")

    except Exception:
        logger.exception("SoilRob failed to start.")
        sys.exit(1)

    finally:
        stop_pollers(pollers)

        logger.info("=" * 60)
        logger.info("SoilRob stopped.")
        logger.info("=" * 60)


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    main()
