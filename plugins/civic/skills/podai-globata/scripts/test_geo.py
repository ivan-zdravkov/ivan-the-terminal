"""Tests for geo.py routing and intersection logic (offline) and mailto.py."""
import json
import subprocess
import sys
import unittest
from pathlib import Path
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import geo  # noqa: E402
import mailto  # noqa: E402


def emails(rs):
    return [r["email"] for r in rs]


class Route(unittest.TestCase):
    def test_sofia_goes_to_cgm_with_sdvr_in_copy(self):
        for args in (("София-град", "Столична"), ("София",), ("Област София-град", "Столична община")):
            r = geo.route(*args)
            self.assertEqual(["office@sofiatraffic.bg"], emails(r["to"]), args)
            self.assertEqual(["trafficpolicesdvr@mvr.bg"], emails(r["cc"]), args)

    def test_sofia_province_is_not_the_city(self):
        r = geo.route("София", "Самоков")
        self.assertEqual(["odmvr-sofia@mvr.bg"], emails(r["to"]))
        self.assertTrue(any("municipal" in x for x in r["lookup"]))

    def test_green_area_in_sofia(self):
        r = geo.route("София-град", "Столична", green=True)
        self.assertEqual(["delovodstvo@inspectorat-so.org"], emails(r["to"]))
        self.assertEqual(["trafficpolicesdvr@mvr.bg"], emails(r["cc"]))

    def test_unknown_police_email_asks_for_lookup(self):
        r = geo.route("Плевен", "Плевен")
        self.assertEqual(([], []), (r["to"], r["cc"]))
        self.assertEqual(2, len(r["lookup"]))

    def test_every_oblast_is_listed(self):
        db = json.loads(geo.DATA.read_text(encoding="utf-8"))
        self.assertEqual(28, len(db["mvr"]))
        for table in ("municipal", "green_area", "mvr"):
            for k, v in db[table].items():
                if v.get("email"):
                    self.assertRegex(v["email"], mailto.EMAIL.pattern, k)
                    self.assertIn(v["confidence"], ("high", "medium"), k)


class Intersection(unittest.TestCase):
    def test_nearest_shared_node_of_two_named_roads(self):
        els = [
            {"type": "way", "id": 1, "nodes": [10, 11, 12], "tags": {"name": "ул. А"}},
            {"type": "way", "id": 2, "nodes": [20, 11], "tags": {"name": "ул. Б"}},
            {"type": "way", "id": 3, "nodes": [12, 30], "tags": {"name": "ул. А"}},  # same street continues
            {"type": "node", "id": 10, "lat": 42.5, "lon": 23.25}, {"type": "node", "id": 11, "lat": 42.5003,
                                                                    "lon": 23.25},
            {"type": "node", "id": 12, "lat": 42.501, "lon": 23.25}, {"type": "node", "id": 20, "lat": 42.5003,
                                                                      "lon": 23.251},
            {"type": "node", "id": 30, "lat": 42.502, "lon": 23.25},
        ]
        self.assertEqual({"streets": ["ул. А", "ул. Б"], "distance_m": 33}, geo.intersection(42.5, 23.25, els))
        self.assertIsNone(geo.intersection(42.5, 23.25, els[:1] + els[3:]))


class Mailto(unittest.TestCase):
    def test_builds_encoded_link(self):
        link = mailto.build({"to": ["a@example.com"], "cc": ["b@example.com", "c@example.com"],
                             "subject": "Сигнал & снимки", "body": "ред 1\nред 2"})
        self.assertTrue(link.startswith("mailto:a@example.com?cc=b%40example.com%2Cc%40example.com&subject="))
        self.assertIn("&body=", link)
        self.assertEqual("ред 1\r\nред 2", unquote(link.split("&body=")[1]))
        self.assertNotIn(" ", link)

    def test_rejects_bad_addresses(self):
        for msg in ({"to": []}, {"to": ["not-an-email"]}, {"to": ["a@example.com"], "cc": ["x@y"]},
                    {"to": ["a@example.com?bcc=evil@example.com"]}):
            with self.assertRaises(ValueError):
                mailto.build(msg)

    def test_cli(self):
        p = subprocess.run([sys.executable, "-I", str(HERE / "mailto.py")], capture_output=True, text=True,
                           input=json.dumps({"to": ["a@example.com"], "subject": "s", "body": "b"}))
        self.assertEqual((0, "mailto:a@example.com?subject=s&body=b\n"), (p.returncode, p.stdout))


if __name__ == "__main__":
    unittest.main()
