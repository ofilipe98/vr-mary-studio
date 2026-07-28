import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from vrsoft_extractor.gui import (
    DEFAULT_CONCURRENCY,
    DEFAULT_MAX_PAGES,
    GuiConfig,
    build_cli_command,
    read_env_file,
    read_inventory_count,
    smoke_test_requested,
    write_env_file,
)
from vrsoft_extractor.settings import DEFAULT_BASE_URL


def _unlink_ignore_errors(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


class GuiTest(unittest.TestCase):
    def test_read_and_write_env_file(self):
        path = Path(".test-tmp") / "gui-env-test.env"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.addCleanup(_unlink_ignore_errors, path)

        write_env_file(
            path,
            GuiConfig(
                email="user@example.com",
                password="secret",
                base_url="https://example.com",
                max_pages=123,
                concurrency=3,
            ),
        )

        loaded = read_env_file(path)
        self.assertEqual(loaded.email, "user@example.com")
        self.assertEqual(loaded.password, "secret")
        self.assertEqual(loaded.base_url, "https://example.com")
        self.assertEqual(loaded.max_pages, 123)
        self.assertEqual(loaded.concurrency, 3)

    def test_read_env_file_uses_defaults(self):
        loaded = read_env_file(Path(".test-tmp") / "missing.env")
        self.assertEqual(loaded.base_url, DEFAULT_BASE_URL)
        self.assertEqual(loaded.max_pages, DEFAULT_MAX_PAGES)
        self.assertEqual(loaded.concurrency, DEFAULT_CONCURRENCY)

    def test_build_cli_command_prefers_venv_exe(self):
        project_dir = Path("D:/project")
        exe = project_dir / ".venv" / "Scripts" / "vrsoft-extractor.exe"
        with patch.object(Path, "exists", return_value=True):
            command = build_cli_command(
                project_dir,
                "download",
                base_url="https://example.com",
                max_pages=10,
                concurrency=4,
            )

        self.assertEqual(command[0], str(exe))
        self.assertIn("download", command)
        self.assertEqual(command[-2:], ["--concurrency", "4"])

    def test_build_cli_command_falls_back_to_module(self):
        with patch.object(Path, "exists", return_value=False):
            command = build_cli_command(Path("D:/project"), "scan")

        self.assertEqual(command[:3], [sys.executable, "-m", "vrsoft_extractor"])
        self.assertIn("scan", command)

    def test_build_cli_command_supports_diagnostic_scan(self):
        with patch.object(Path, "exists", return_value=False):
            command = build_cli_command(Path("D:/project"), "diagnostic-scan")

        self.assertIn("scan", command)
        self.assertIn("--diagnostic", command)

    def test_build_cli_command_rejects_unknown_action(self):
        with self.assertRaises(ValueError):
            build_cli_command(Path("D:/project"), "unknown")

    def test_smoke_test_requested(self):
        self.assertTrue(smoke_test_requested(["--smoke-test"]))
        self.assertFalse(smoke_test_requested(["--project-dir", "D:/project"]))

    def test_read_inventory_count(self):
        project_dir = Path(".test-tmp") / "gui-inventory-test"
        inventory_path = project_dir / "metadata" / "videos.json"
        inventory_path.parent.mkdir(parents=True, exist_ok=True)
        inventory_path.write_text("[{}, {}]", encoding="utf-8")

        self.assertEqual(read_inventory_count(project_dir), 2)


if __name__ == "__main__":
    unittest.main()
