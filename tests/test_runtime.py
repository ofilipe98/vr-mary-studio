import unittest
from unittest.mock import patch

from vrsoft_extractor.runtime import configure_playwright_runtime


class RuntimeTest(unittest.TestCase):
    def test_configure_playwright_runtime_sets_local_browser_path(self):
        with patch.dict("os.environ", {}, clear=True):
            configure_playwright_runtime()
            import os

            self.assertEqual(os.environ["PLAYWRIGHT_BROWSERS_PATH"], "0")


if __name__ == "__main__":
    unittest.main()
