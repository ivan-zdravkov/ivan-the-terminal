import tempfile
import unittest
from pathlib import Path

import envfile


class Env(unittest.TestCase):
    def test_quotes_comments_and_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "config.env")
            p.write_text('# comment\nA="x # kept"\nB=plain  # dropped\nC=\'single\'\nlower=ignored\n', encoding="utf-8")
            cfg = envfile.env(p, {"A": "", "D": "default"})
        self.assertEqual({"A": "x # kept", "B": "plain", "C": "single", "D": "default"}, cfg)

    def test_missing_file_gives_defaults(self):
        self.assertEqual({"X": "1"}, envfile.env("/nonexistent/config.env", {"X": "1"}))


if __name__ == "__main__":
    unittest.main()
