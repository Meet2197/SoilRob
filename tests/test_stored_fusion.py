import json
import tempfile
import unittest
from pathlib import Path

from src.fusion.fusion_engine import FusionEngine


class StoredFusionTests(unittest.TestCase):
    def test_synchronize_stored_data_pairs_and_archives_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            thermal_dir = base / "thermal"
            hsi_dir = base / "hsi"
            thermal_dir.mkdir()
            hsi_dir.mkdir()

            thermal_records = [
                {
                    "timestamp_utc": 100.0,
                    "record_id": "thermal-100",
                    "temp_f": 68.0,
                    "box1_min_c": 18.0,
                    "box1_max_c": 22.0,
                    "box1_avg_c": 20.0,
                },
                {"timestamp_utc": 101.0, "record_id": "thermal-101", "temp_f": 86.0},
            ]
            hsi_records = [
                {"timestamp_utc": 99.1, "record_id": "hsi-99", "serial_number": "BB-1"},
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
                "sites": {"site_A": {"crs_native": "EPSG:4326"}},
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
            with Path(result["output_file"]).open(encoding="utf-8") as handle:
                fused = json.load(handle)
            self.assertEqual([record["temperature_c"] for record in fused], [20.0, 30.0])
            self.assertEqual(fused[0]["thermal_min_c"], 18.0)
            self.assertEqual(fused[0]["thermal_max_c"], 22.0)
            self.assertEqual(fused[0]["thermal_avg_c"], 20.0)
            self.assertEqual(fused[0]["source_records"], {"thermal": "thermal-100", "hsi": "hsi-99"})
            self.assertEqual(fused[0]["hsi_serial_number"], "BB-1")


if __name__ == "__main__":
    unittest.main()