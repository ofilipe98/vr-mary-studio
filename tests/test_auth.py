import unittest
from unittest.mock import patch

from vrsoft_extractor.auth import _should_wait_without_prompt


class AuthTest(unittest.TestCase):
    def test_should_wait_without_prompt_in_gui_mode(self):
        with patch.dict("os.environ", {"ENDOO_GUI_MODE": "1"}, clear=False):
            self.assertTrue(_should_wait_without_prompt())


if __name__ == "__main__":
    unittest.main()
