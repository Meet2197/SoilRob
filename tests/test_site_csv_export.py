import json
import tempfile
import unittest
from pathlib import Path

from src.fusion.fusion_engine import FusionEngine


class SiteCsvExportTests(unittest.TestCase):
    def test_export_site_qa_log_creates_csv(self):
        config = {
            "fusion": {"time_tolerance_s": 1.0, "buffer_size": 50},
            "sites": {
                "site_A": {
                    "thermal": {
                        "temporary_dir": "data/thermal_temp/site_A",
                        "evaluation_dir": "data/thermal_evaluation/site_A",
                        "qa": {"min_temperature_c": -40, "max_temperature_c": 150},
                    }
                }
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            site_dir = base / "data" / "thermal_temp" / "site_A"
            site_dir.mkdir(parents=True, exist_ok=True)
            (site_dir / "thermal_1.json").write_text(json.dumps({"timestamp_utc": 100.0, "record_id": "site_A_1", "temp_f": 99.0}), encoding="utf-8")
            (site_dir / "thermal_2.json").write_text(json.dumps({"timestamp_utc": 101.0, "record_id": "site_A_2", "thermal_temperature": 42.0}), encoding="utf-8")

            engine = FusionEngine(config)
            engine._sensor_dirs = lambda site_id, sensor_type: (site_dir, base / "data" / "thermal_evaluation" / site_id)
            engine.export_site_qa_log("site_A", "thermal")

            csv_path = base / "data" / "thermal_evaluation" / "site_A" / "site_A_thermal_qa_log.csv"
            self.assertTrue(csv_path.exists())
            text = csv_path.read_text(encoding="utf-8")
            self.assertIn("qa_pass", text)
            self.assertIn("site_A", text)
            self.assertIn("42.0", text)


if __name__ == "__main__":
    unittest.main()
