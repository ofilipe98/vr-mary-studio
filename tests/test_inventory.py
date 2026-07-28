import json
import shutil
import unittest
import uuid
from pathlib import Path

from vrsoft_extractor.inventory import load_inventory, merge_inventory, save_inventory
from vrsoft_extractor.models import VideoItem


class InventoryTest(unittest.TestCase):
    def test_save_and_load_inventory(self):
        tmp_path = Path(".test-tmp") / uuid.uuid4().hex
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        item = VideoItem(
            area="biblioteca",
            course="",
            module="",
            lesson_title="Aula 1",
            page_url="https://example.com/aula",
            media_url="https://cdn.example.com/aula.mp4",
            media_type="mp4",
        )
        json_path = tmp_path / "videos.json"
        csv_path = tmp_path / "videos.csv"
        save_inventory([item], json_path, csv_path)

        loaded = load_inventory(json_path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].lesson_title, "Aula 1")
        self.assertTrue(csv_path.exists())
        self.assertEqual(
            json.loads(json_path.read_text(encoding="utf-8"))[0]["media_type"],
            "mp4",
        )

    def test_merge_inventory_preserves_downloaded_status(self):
        old = VideoItem(
            area="curso",
            course="Curso",
            module="Modulo",
            lesson_title="Aula",
            page_url="https://example.com/aula",
            media_url="https://cdn.example.com/aula.mp4",
            media_type="mp4",
            status="downloaded",
            local_path="downloads/aula.mp4",
        )
        new = VideoItem(
            area="curso",
            course="Curso",
            module="Modulo atualizado",
            lesson_title="Aula",
            page_url="https://example.com/aula",
            media_url="https://cdn.example.com/aula.mp4",
            media_type="mp4",
        )

        merged = merge_inventory([old], [new])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].status, "downloaded")
        self.assertEqual(merged[0].local_path, "downloads/aula.mp4")
        self.assertEqual(merged[0].module, "Modulo atualizado")


if __name__ == "__main__":
    unittest.main()
