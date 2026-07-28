import json
import shutil
import unittest
import uuid
from pathlib import Path

from vrsoft_extractor.cookies import write_netscape_cookie_file


class CookiesTest(unittest.TestCase):
    def test_write_netscape_cookie_file(self):
        tmp_path = Path(".test-tmp") / uuid.uuid4().hex
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))
        state = {
            "cookies": [
                {
                    "name": "session",
                    "value": "abc",
                    "domain": ".example.com",
                    "path": "/",
                    "expires": 2000000000,
                    "secure": True,
                }
            ],
            "origins": [],
        }
        state_path = tmp_path / "state.json"
        cookie_path = tmp_path / "cookies.txt"
        state_path.write_text(json.dumps(state), encoding="utf-8")

        write_netscape_cookie_file(state_path, cookie_path)

        content = cookie_path.read_text(encoding="utf-8")
        self.assertIn(".example.com\tTRUE\t/\tTRUE\t2000000000\tsession\tabc", content)


if __name__ == "__main__":
    unittest.main()
