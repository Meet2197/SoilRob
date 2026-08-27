"""Convert FLIR and HAIP BlackBullet image exports into QA-ready CSV rows."""
from __future__ import annotations

import argparse
import hashlib
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as image_file:
        for block in iter(lambda: image_file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def qa_image(path: Path, sensor_type: str, site_id: str) -> dict:
    """Read one image and return metadata plus a deterministic QA result."""
    row = {
        "site_id": site_id,
        "sensor_type": sensor_type,
        "image_path": str(path),
        "filename": path.name,
        "format": path.suffix.lower().lstrip("."),
        "width_px": None,
        "height_px": None,
        "channels": None,
        "dtype": None,
        "min_pixel": None,
        "max_pixel": None,
        "mean_pixel": None,
        "std_pixel": None,
        "file_size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "qa_pass": False,
        "qa_error": None,
    }
    try:
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            pixels = np.asarray(image)
            if pixels.size == 0 or not np.isfinite(pixels).all():
                raise ValueError("image has no finite pixel values")
            row.update({
                "format": (image.format or path.suffix).lower().lstrip("."),
                "width_px": image.width,
                "height_px": image.height,
                "channels": 1 if pixels.ndim == 2 else pixels.shape[2],
                "dtype": str(pixels.dtype),
                "min_pixel": float(pixels.min()),
                "max_pixel": float(pixels.max()),
                "mean_pixel": float(pixels.mean()),
                "std_pixel": float(pixels.std()),
                "qa_pass": image.width > 0 and image.height > 0,
            })
    except Exception as exc:
        row["qa_error"] = str(exc)
        logger.warning("Image QA failed for %s: %s", path, exc)
    return row


def images_to_csv(image_dir: str | Path, csv_path: str | Path,
                  sensor_type: str, site_id: str) -> pd.DataFrame:
    """Convert supported images in ``image_dir`` to a CSV and return the rows."""
    source_dir = Path(image_dir)
    output_path = Path(csv_path)
    if not source_dir.is_dir():
        raise NotADirectoryError(f"Image directory not found: {source_dir}")
    paths = sorted(path for path in source_dir.rglob("*")
                   if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS)
    rows = [qa_image(path, sensor_type, site_id) for path in paths]
    columns = list(rows[0]) if rows else [
        "site_id", "sensor_type", "image_path", "filename", "format",
        "width_px", "height_px", "channels", "dtype", "min_pixel",
        "max_pixel", "mean_pixel", "std_pixel", "file_size_bytes", "sha256",
        "qa_pass", "qa_error",
    ]
    frame = pd.DataFrame(rows, columns=columns)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False)
    logger.info("Wrote %d image QA rows to %s", len(frame), output_path)
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image_dir", type=Path)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--sensor-type", required=True, choices=("flir", "blackbullet"))
    parser.add_argument("--site-id", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    images_to_csv(args.image_dir, args.csv_path, args.sensor_type, args.site_id)


if __name__ == "__main__":
    main()