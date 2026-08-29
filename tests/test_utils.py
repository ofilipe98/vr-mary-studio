import re
import tomllib
import unittest
from pathlib import Path

from vrsoft_extractor import __version__
from vrsoft_extractor.utils import classify_media_url, output_base_path, sanitize_filename


class UtilsTest(unittest.TestCase):
    def test_windows_launcher_uses_relocatable_python_module_entrypoint(self):
        root = Path(__file__).parents[1]
        launcher = (root / "Start-VRStudio.bat").read_text(encoding="utf-8")

        self.assertIn(r".venv\Scripts\python.exe", launcher)
        self.assertIn("-m vrsoft_extractor.mary.frontend.app", launcher)
        self.assertNotIn("vr-norte-studio.exe", launcher)
        self.assertNotIn("vr-mary-studio.exe", launcher)

    def test_version_is_synchronized_across_source_and_installer(self):
        root = Path(__file__).parents[1]
        project_version = tomllib.loads(
            (root / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]["version"]
        installer = (root / "installer" / "VRNorteStudio.iss").read_text(
            encoding="utf-8"
        )
        executable_version = (
            root / "installer" / "VRNorteStudio.version.txt"
        ).read_text(encoding="utf-8")
        match = re.search(r'^#define MyAppVersion "([^"]+)"$', installer, re.MULTILINE)
        product_match = re.search(
            r"StringStruct\('ProductVersion', '([^']+)'\)", executable_version
        )
        file_match = re.search(
            r"StringStruct\('FileVersion', '([^']+)'\)", executable_version
        )
        fixed_match = re.search(
            r"filevers=\((\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)",
            executable_version,
        )
        parsed_version = re.fullmatch(r"(\d+)\.(\d+)(?:-(\d+))?", project_version)

        self.assertIsNotNone(match)
        self.assertIsNotNone(product_match)
        self.assertIsNotNone(file_match)
        self.assertIsNotNone(fixed_match)
        self.assertIsNotNone(parsed_version)
        self.assertEqual(project_version, __version__)
        self.assertEqual(match.group(1), __version__)
        self.assertEqual(product_match.group(1), __version__)
        self.assertEqual(file_match.group(1), __version__)
        major, minor, revision = parsed_version.groups()
        expected_fixed = (
            int(major),
            int(minor),
            0,
            int(revision or 0),
        )
        self.assertEqual(
            tuple(int(value) for value in fixed_match.groups()), expected_fixed
        )

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
