import tempfile
import unittest
from pathlib import Path

from PIL import Image

from src.ui.haip_dashboard import HSIImageScheduler


class HsiImageSchedulerTests(unittest.TestCase):
    def test_generated_image_is_saved_in_data_and_output_folders(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            scheduler = HSIImageScheduler(tmpdir)

            image_path = Path(scheduler.generate_image("site_A", "snapshot"))
            output_path = Path(tmpdir) / "output" / "site_A" / "snapshot" / image_path.name

            self.assertTrue(image_path.is_file())
            self.assertTrue(output_path.is_file())
            with Image.open(image_path) as image:
                self.assertEqual(image.size, (1200, 600))
            with Image.open(output_path) as image:
                self.assertEqual(image.size, (1200, 600))


if __name__ == "__main__":
    unittest.main()
