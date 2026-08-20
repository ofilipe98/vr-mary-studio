import unittest
from unittest.mock import patch

from vrsoft_extractor.auth import (
    EMAIL_SELECTORS,
    _has_visible,
    _should_wait_without_prompt,
)


class AuthTest(unittest.TestCase):
    def test_current_endoo_username_field_is_supported(self):
        self.assertIn("#username", EMAIL_SELECTORS)

    def test_has_visible_handles_two_step_login_field(self):
        page = unittest.mock.MagicMock()
        hidden = unittest.mock.MagicMock()
        hidden.count.return_value = 1
        hidden.is_visible.return_value = False
        visible = unittest.mock.MagicMock()
        visible.count.return_value = 1
        visible.is_visible.return_value = True
        page.locator.side_effect = [hidden, visible]

        self.assertTrue(_has_visible(page, ["#username", "#password"]))

    def test_should_wait_without_prompt_in_gui_mode(self):
        with patch.dict("os.environ", {"ENDOO_GUI_MODE": "1"}, clear=False):
            self.assertTrue(_should_wait_without_prompt())


if __name__ == "__main__":
    unittest.main()
