import unittest
from pathlib import Path

from vrsoft_extractor.utils import classify_media_url, output_base_path, sanitize_filename


class UtilsTest(unittest.TestCase):
    def test_sanitize_filename_removes_windows_invalid_chars(self):
        self.assertEqual(sanitize_filename(' Aula: "PDV" / Frente? '), "Aula_ _PDV_ _ Frente_")

    def test_sanitize_filename_handles_reserved_names(self):
        self.assertEqual(sanitize_filename("CON"), "CON_")

    def test_classify_media_url(self):
        self.assertEqual(classify_media_url("https://cdn.example.com/aula.mp4?token=1"), "mp4")
        self.assertEqual(classify_media_url("https://cdn.example.com/master.m3u8"), "hls")
        self.assertEqual(classify_media_url("https://player.vimeo.com/video/123"), "embed")
        self.assertEqual(classify_media_url("https://videos.example.com/player/123"), "embed")
        self.assertEqual(classify_media_url("https://example.com/aula"), "unknown")

    def test_output_base_path_uses_expected_area_dirs(self):
        path = output_base_path(Path("downloads"), "curso", "Curso: PDV", "Modulo/1", "Aula*1")
        self.assertEqual(
            path,
            Path("downloads") / "Cursos" / "Curso_ PDV" / "Modulo_1" / "Aula_1",
        )


if __name__ == "__main__":
    unittest.main()
