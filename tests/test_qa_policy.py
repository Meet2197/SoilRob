import pandas as pd
import unittest

from src.qa.qa_protocol import run_qa_pipeline


class QaPolicyTests(unittest.TestCase):
    def test_temperature_range_is_enforced(self):
        config = {
            "sites": {
                "site_A": {
                    "crs_native": "EPSG:4326",
                    "thermal": {
                        "qa": {
                            "min_temperature_c": -40,
                            "max_temperature_c": 150,
                            "max_missing_fraction": 0.05,
                            "max_jump_c": 15,
                            "max_rate_c_per_s": 5,
                            "min_valid_samples": 1,
                        }
                    },
                }
            }
        }
        record = {
            "site_id": "site_A",
            "record_id": "site_A_1",
            "timestamp_utc": 100.0,
            "temperature_c": 200,
            "crs": "EPSG:4326",
        }
        history = pd.DataFrame([
            {"timestamp_utc": 90.0, "temperature_c": 20.0},
        ])

        report = run_qa_pipeline(
            record,
            history,
            config,
            last_ts=50.0,
            required_fields=["temperature_c", "crs"],
            numeric_field="temperature_c",
        )

        self.assertFalse(report["overall_pass"])
        self.assertTrue(any(check["check"] == "temperature_bounds" for check in report["checks"]))


if __name__ == "__main__":
    unittest.main()
