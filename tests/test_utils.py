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
        revision_version = re.fullmatch(
            r"(\d+)\.(\d+)(?:-(\d+))?", project_version
        )
        patch_version = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", project_version)
        patch_revision_version = re.fullmatch(
            r"(\d+)\.(\d+)\.(\d+)-(\d+)", project_version
        )
        beta_version = re.fullmatch(
            r"(\d+)\.(\d+)\.(\d+)b(\d+)", project_version
        )

        self.assertIsNotNone(match)
        self.assertIsNotNone(product_match)
        self.assertIsNotNone(file_match)
        self.assertIsNotNone(fixed_match)
        product_fixed_match = re.search(r"prodvers=\((\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)", executable_version)
        self.assertIsNotNone(product_fixed_match)
        self.assertEqual(product_fixed_match.groups(), fixed_match.groups())
        self.assertTrue(
            revision_version or patch_version or patch_revision_version or beta_version
        )
        self.assertEqual(project_version, __version__)
        self.assertEqual(match.group(1), __version__)
        self.assertEqual(product_match.group(1), __version__)
        self.assertEqual(file_match.group(1), __version__)
        if beta_version:
            major, minor, patch, beta = beta_version.groups()
            expected_fixed = (int(major), int(minor), int(patch), int(beta))
        elif patch_revision_version:
            major, minor, patch, revision = patch_revision_version.groups()
            expected_fixed = (int(major), int(minor), int(patch), int(revision))
        elif patch_version:
            major, minor, patch = patch_version.groups()
            expected_fixed = (int(major), int(minor), int(patch), 0)
        else:
            assert revision_version is not None
            major, minor, revision = revision_version.groups()
            expected_fixed = (int(major), int(minor), 0, int(revision or 0))
        self.assertEqual(
            tuple(int(value) for value in fixed_match.groups()), expected_fixed
        )

    def test_portable_build_prepares_hermetic_chromium_before_packaging(self):
        script = (Path(__file__).parents[1] / "build_portable.ps1").read_text(encoding="utf-8")
        preparation = script.index("ensure_playwright_chromium(allow_install=True)")
        packaging = script.index("& $Python -m PyInstaller")
        self.assertLess(script.index('$env:PLAYWRIGHT_BROWSERS_PATH = "0"'), preparation)
        self.assertIn('& $Python -c "from vrsoft_extractor.runtime import', script)
        self.assertLess(preparation, packaging)
        self.assertIn("if ($LASTEXITCODE -ne 0)", script[preparation:packaging])
        self.assertIn('throw "Preparacao do Chromium', script[preparation:packaging])
        for binary in ('-Filter "chrome.exe"', '-Filter "ffmpeg-win64.exe"'):
            self.assertGreater(script.index(binary), packaging)
        self.assertEqual(script.count('Where-Object { $_.FullName -like "*playwright*'), 2)
        self.assertIn("if (-not $BundledBrowser -or -not $BundledFfmpeg)", script)

    def test_portable_build_uses_zip64_capable_archiver(self):
        root = Path(__file__).parents[1]
        build_script = (root / "build_portable.ps1").read_text(encoding="utf-8")

        self.assertIn(
            "& $Python -m zipfile -c $PortableArchive $PortableRoot", build_script
        )
        self.assertNotRegex(build_script, r"(?m)^\s*Compress-Archive\b")
        self.assertLess(
            build_script.index("-m zipfile -c"),
            build_script.index("Get-FileHash -LiteralPath $PortableArchive"),
        )

    def test_portable_build_uses_local_vrproject_and_requires_code_toolchain(self):
        root = Path(__file__).parents[1]
        build_script = (root / "build_portable.ps1").read_text(encoding="utf-8")

        self.assertIn('Join-Path $ProjectRoot "VRProject"', build_script)
        self.assertIn('@("--root", $ResolvedVRRoot)', build_script)
        self.assertNotIn('if ($VRRoot) {\n            $ExportArguments', build_script)
        self.assertIn('"decompilers\\vineflower-1.12.0.jar"', build_script)
        self.assertIn('"decompilers\\cfr-0.152.jar"', build_script)
        self.assertIn('Filter "java.exe"', build_script)

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
