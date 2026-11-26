import csv
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from src.fusion.fusion_engine import FusionEngine


class StoredFusionTests(unittest.TestCase):
    def test_synchronize_stored_data_pairs_and_archives_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            thermal_dir = base / "thermal"
            hsi_dir = base / "hsi"
            thermal_dir.mkdir()
            hsi_dir.mkdir()
            source_images = base / "source_images"
            source_images.mkdir()
            thermal_image = source_images / "thermal.png"
            hsi_image = source_images / "hsi.img"
            Image.new("RGB", (4, 3), "red").save(thermal_image)
            hsi_image.write_bytes(b"hyperspectral image data")
            hsi_image.with_suffix(".hdr").write_text("ENVI header", encoding="utf-8")

            thermal_records = [
                {
                    "timestamp_utc": 100.0,
                    "record_id": "thermal-100",
                    "temp_f": 68.0,
                    "box1_min_c": 18.0,
                    "box1_max_c": 22.0,
                    "box1_avg_c": 20.0,
                    "image_path": str(thermal_image),
                    "latitude": 51.5,
                    "longitude": -0.1,
                },
                {"timestamp_utc": 101.0, "record_id": "thermal-101", "temp_f": 86.0},
            ]
            hsi_records = [
                {
                    "timestamp_utc": 99.1,
                    "record_id": "hsi-99",
                    "serial_number": "BB-1",
                    "gain": 1.5,
                    "exposure_us": 10000,
                    "capture_id": "capture-99",
                    "image_path": str(hsi_image),
                },
                {"timestamp_utc": 100.4, "record_id": "hsi-100", "serial_number": "BB-1"},
            ]
            for index, record in enumerate(thermal_records):
                (thermal_dir / f"thermal_{index}.json").write_text(
                    json.dumps(record), encoding="utf-8"
                )
            for index, record in enumerate(hsi_records):
                (hsi_dir / f"hsi_{index}.json").write_text(
                    json.dumps(record), encoding="utf-8"
                )

            engine = FusionEngine({
                "fusion": {
                    "time_tolerance_s": 1.0,
                    "buffer_size": 10,
                    "archive_dir": str(base / "archive"),
                },
                "sites": {
                    "site_A": {
                        "crs_native": "EPSG:4326",
                        "thermal": {"image_dir": str(base / "images" / "site_A" / "thermal")},
                        "hsi": {"image_dir": str(base / "images" / "site_A" / "hsi")},
                    }
                },
            })
            engine._sensor_dirs = lambda site_id, sensor_type: (
                thermal_dir if sensor_type == "thermal" else hsi_dir,
                base / "evaluation",
            )

            result = engine.synchronize_stored_data("site_A")

            self.assertEqual(result["matched_count"], 2)
            self.assertEqual(result["unmatched_thermal_count"], 0)
            self.assertEqual(result["unmatched_hsi_count"], 0)
            self.assertTrue(Path(result["output_dir"]).is_dir())
            csv_path = Path(result["csv_file"])
            self.assertTrue(csv_path.is_file())
            csv_text = csv_path.read_text(encoding="utf-8")
            self.assertIn("sensor_type", csv_text)
            self.assertIn("fused_thermal_hsi", csv_text)
            with csv_path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertTrue({
                    "thermal_timestamp_utc",
                    "thermal_record_id",
                    "capture_id",
                    "thermal_image_path",
                    "hsi_timestamp_utc",
                    "hsi_record_id",
                    "hsi_serial_number",
                    "hsi_capture_id",
                    "hsi_image_path",
                    "latitude",
                    "longitude",
                    "crs",
                    "source_records",
                    "time_delta_s",
                    "fused",
                }.issubset(reader.fieldnames))
                rows = list(reader)
            fused_row = next(row for row in rows if row["fused"] == "True")
            self.assertEqual(fused_row["thermal_record_id"], "thermal-100")
            self.assertEqual(fused_row["hsi_record_id"], "hsi-99")
            self.assertEqual(fused_row["hsi_capture_id"], "capture-99")
            self.assertEqual(fused_row["latitude"], "51.5")
            self.assertEqual(fused_row["longitude"], "-0.1")
            self.assertEqual(
                json.loads(fused_row["source_records"]),
                {"thermal": "thermal-100", "hsi": "hsi-99"},
            )
            thermal_saved = Path(fused_row["thermal_image_path"])
            hsi_saved = Path(fused_row["hsi_image_path"])
            self.assertTrue(thermal_saved.is_file())
            self.assertTrue(hsi_saved.is_file())
            self.assertTrue(hsi_saved.with_suffix(".hdr").is_file())
            self.assertEqual(thermal_saved.parent, Path(result["thermal_image_dir"]))
            self.assertEqual(hsi_saved.parent, Path(result["hsi_image_dir"]))
            self.assertNotEqual(thermal_saved.parent, hsi_saved.parent)
            with Path(result["output_file"]).open(encoding="utf-8") as handle:
                fused = json.load(handle)
            self.assertEqual([record["temperature_c"] for record in fused], [20.0, 30.0])
            self.assertEqual(fused[0]["thermal_min_c"], 18.0)
            self.assertEqual(fused[0]["thermal_max_c"], 22.0)
            self.assertEqual(fused[0]["thermal_avg_c"], 20.0)
            self.assertEqual(fused[0]["source_records"], {"thermal": "thermal-100", "hsi": "hsi-99"})
            self.assertEqual(fused[0]["hsi_serial_number"], "BB-1")

    def test_hsi_capture_id_discovers_native_img_and_header(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            image_dir = base / "images" / "site_A" / "hsi"
            image_dir.mkdir(parents=True)
            image_path = image_dir / "site_A_capture-1.img"
            image_path.write_bytes(b"hyperspectral image data")
            header_path = image_path.with_suffix(".hdr")
            header_path.write_text("ENVI header", encoding="utf-8")

            engine = FusionEngine({
                "fusion": {"time_tolerance_s": 1.0, "buffer_size": 10},
                "sites": {
                    "site_A": {
                        "hsi": {"image_dir": str(image_dir)},
                    }
                },
            })
            raw = {
                "capture_id": "site_A_capture-1",
                "timestamp_utc": 100.0,
            }

            engine._persist_sensor_image("site_A", "hsi", raw)

            self.assertEqual(raw["image_path"], str(image_path))
            self.assertTrue(header_path.is_file())

    def test_hsi_capture_id_copies_matching_line_scan_exports(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            source_dir = base / "line_scan"
            image_dir = base / "Data fusion" / "HAIP_BlackBullet"
            source_dir.mkdir()
            image_dir.mkdir(parents=True)
            capture_id = "site_A_capture-2"
            source_files = [
                source_dir / f"timestamp_{capture_id}_raw.img",
                source_dir / f"timestamp_{capture_id}_raw.hdr",
                source_dir / f"timestamp_{capture_id}.png",
                source_dir / f"timestamp_{capture_id}_FS.tif",
            ]
            for path in source_files:
                path.write_bytes(b"capture data")

            engine = FusionEngine({
                "fusion": {"time_tolerance_s": 1.0, "buffer_size": 10},
                "sites": {
                    "site_A": {
                        "hsi": {
                            "image_dir": str(image_dir),
                            "image_source_dir": str(source_dir),
                        },
                    }
                },
            })
            raw = {"capture_id": capture_id, "timestamp_utc": 100.0}

            engine._persist_sensor_image("site_A", "hsi", raw)

            saved_img = image_dir / source_files[0].name
            self.assertEqual(raw["image_path"], str(saved_img))
            for source_file in source_files:
                self.assertEqual(
                    (image_dir / source_file.name).read_bytes(),
                    source_file.read_bytes(),
                )

    def test_hsi_capture_id_copies_matching_line_scan_exports(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            source_dir = base / "line_scan"
            image_dir = base / "Data fusion" / "HAIP_BlackBullet"
            source_dir.mkdir()
            image_dir.mkdir(parents=True)
            capture_id = "site_A_capture-2"
            source_files = [
                source_dir / f"timestamp_{capture_id}_raw.img",
                source_dir / f"timestamp_{capture_id}_raw.hdr",
                source_dir / f"timestamp_{capture_id}.png",
                source_dir / f"timestamp_{capture_id}_FS.tif",
            ]
            for path in source_files:
                path.write_bytes(b"capture data")

            engine = FusionEngine({
                "fusion": {"time_tolerance_s": 1.0, "buffer_size": 10},
                "sites": {
                    "site_A": {
                        "hsi": {
                            "image_dir": str(image_dir),
                            "image_source_dir": str(source_dir),
                        },
                    }
                },
            })
            raw = {"capture_id": capture_id, "timestamp_utc": 100.0}

            engine._persist_sensor_image("site_A", "hsi", raw)

            saved_img = image_dir / source_files[0].name
            self.assertEqual(raw["image_path"], str(saved_img))
            for source_file in source_files:
                self.assertEqual(
                    (image_dir / source_file.name).read_bytes(),
                    source_file.read_bytes(),
                )


if __name__ == "__main__":
    unittest.main()