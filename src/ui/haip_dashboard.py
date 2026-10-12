from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Dict, Optional

from PIL import Image, ImageDraw


class HSIImageScheduler:
    def __init__(self, base_dir: str | Path | None = None):
        self.base_dir = Path(base_dir) if base_dir is not None else Path(__file__).resolve().parents[2]
        self._lock = threading.Lock()
        self._threads: Dict[str, threading.Thread] = {}
        self._stop_events: Dict[str, threading.Event] = {}
        self._last_images: Dict[str, str] = {}

    def _image_dir(self, site_id: str, mode: str) -> Path:
        out_dir = self.base_dir / "data" / "haip_ui" / site_id / mode
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    def generate_image(self, site_id: str, mode: str, exposure_us: int = 7000, gain: float = 10.0) -> str:
        out_dir = self._image_dir(site_id, mode)
        timestamp = int(time.time() * 1000)
        image = Image.new("RGB", (1200, 600), (15, 15, 20))
        draw = ImageDraw.Draw(image)

        # Background banding for a line-scan feel
        for y in range(0, image.height, 20):
            shade = 20 + ((y // 20) % 10) * 12
            draw.rectangle([0, y, image.width, y + 18], fill=(shade, shade, shade + 5))

        if mode == "line_scan":
            draw.rectangle([40, 80, image.width - 40, image.height - 80], outline=(90, 180, 255), width=3)
            for x in range(60, image.width - 60, 25):
                y_center = 130 + ((x // 30) % 5) * 35
                draw.line((x, y_center, x + 20, y_center + 60), fill=(120, 200, 255), width=3)
            draw.text((50, 30), f"HAIP line-scan | site={site_id}", fill=(220, 240, 255))
            draw.text((50, image.height - 60), f"Exposure={exposure_us}us  Gain={gain}x", fill=(220, 240, 255))
        elif mode == "snapshot":
            draw.rectangle([80, 100, image.width - 80, image.height - 100], outline=(120, 220, 180), width=4)
            for gx in range(120, image.width - 120, 80):
                draw.line((gx, 100, gx, image.height - 100), fill=(60, 90, 110), width=2)
            for gy in range(120, image.height - 120, 80):
                draw.line((80, gy, image.width - 80, gy), fill=(60, 90, 110), width=2)
            draw.text((100, 40), f"Snapshot | site={site_id}", fill=(220, 255, 240))
            draw.text((100, image.height - 60), f"Exposure={exposure_us}us  Gain={gain}x", fill=(220, 255, 240))
        else:
            draw.rectangle([60, 80, image.width - 60, image.height - 80], outline=(255, 180, 90), width=4)
            for x in range(80, image.width - 80, 60):
                y = 140 + 100 * ((x // 60) % 2)
                draw.line((x, 100, x, image.height - 100), fill=(255, 160, 90), width=3)
                draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=(255, 224, 120))
            draw.text((90, 30), f"HSI livestream | site={site_id}", fill=(255, 238, 200))
            draw.text((90, image.height - 60), f"Exposure={exposure_us}us  Gain={gain}x", fill=(255, 238, 200))

        path = out_dir / f"{mode}_{timestamp}.png"
        image.save(path)
        self._last_images[f"{site_id}:{mode}"] = str(path)
        return str(path)

    def start(self, site_id: str, mode: str = "snapshot", interval_s: float = 30.0, exposure_us: int = 7000, gain: float = 10.0) -> str:
        key = f"{site_id}:{mode}"
        with self._lock:
            if key in self._threads and self._threads[key].is_alive():
                return self._last_images.get(key, "")
            stop_event = threading.Event()
            self._stop_events[key] = stop_event

            def _worker():
                while not stop_event.is_set():
                    self.generate_image(site_id, mode, exposure_us=exposure_us, gain=gain)
                    if interval_s > 0:
                        stop_event.wait(interval_s)
                    else:
                        break

            thread = threading.Thread(target=_worker, daemon=True)
            self._threads[key] = thread
            thread.start()
            return self._last_images.get(key, "")

    def stop(self, site_id: str, mode: str = "snapshot") -> None:
        key = f"{site_id}:{mode}"
        with self._lock:
            stop_event = self._stop_events.get(key)
            if stop_event is not None:
                stop_event.set()
            self._stop_events.pop(key, None)
            thread = self._threads.pop(key, None)
            if thread is not None and thread.is_alive():
                thread.join(timeout=1.0)

    def latest_images(self) -> dict:
        with self._lock:
            return dict(self._last_images)


scheduler = HSIImageScheduler()
