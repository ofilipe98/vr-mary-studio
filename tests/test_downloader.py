import json
import shutil
import unittest
import uuid
from pathlib import Path

from vrsoft_extractor.downloader import download_inventory
from vrsoft_extractor.settings import ConfigError, Settings


class DownloaderTest(unittest.TestCase):
    def test_download_inventory_reports_empty_inventory(self):
        project_dir = Path(".test-tmp") / uuid.uuid4().hex
        metadata_dir = project_dir / "metadata"
        metadata_dir.mkdir(parents=True, exist_ok=True)
        (metadata_dir / "videos.json").write_text(json.dumps([]), encoding="utf-8")
        self.addCleanup(lambda: shutil.rmtree(project_dir, ignore_errors=True))

        with self.assertRaisesRegex(ConfigError, "Inventario vazio"):
            download_inventory(Settings(project_dir=project_dir))


if __name__ == "__main__":
    unittest.main()

