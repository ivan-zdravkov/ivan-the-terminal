import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
TMP = tempfile.mkdtemp()
TOKEN = "t" * 20
Path(TMP, "config.env").write_text(f'TOKEN="{TOKEN}"\nPORT=0  # comment\nTRIGGER="true"\nLEVEL_NAMES="White,Yellow"\n')
os.environ.update(DAILY_COACH_CONF=str(Path(TMP, "config.env")), DAILY_COACH_DATA=TMP)
spec = importlib.util.spec_from_file_location("coach", HERE / "coach.py")
coach = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coach)


def iso(day, hour, minute=0):
    return (datetime(day.year, day.month, day.day) + timedelta(hours=hour, minutes=minute)).astimezone().isoformat()


def plan(**kw):
    return {"readiness": "green", "headline": "Go", "items": [
        {"id": "pushups", "kind": "check", "label": "10 push-ups", "xp": 10, "core": True, "cat": "move"},
        {"id": "weight", "kind": "number", "label": "Weight", "metric": "weight_kg", "xp": 5, "cat": "measure"},
        {"id": "energy", "kind": "scale", "label": "Energy", "xp": 3}], **kw}


class CoachTest(unittest.TestCase):
    def setUp(self):
        self.con = coach.db()
        for t in ("samples", "plans", "checks", "events"):
            self.con.execute(f"DELETE FROM {t}")
        self.con.commit()
        self.day = coach.today()
        self.prev = self.day - timedelta(days=1)

    def tearDown(self):
        self.con.commit()
        self.con.close()

    def test_config_parsing(self):
        self.assertEqual(coach.CFG["PORT"], "0")
        self.assertEqual(coach.CFG["TOKEN"], TOKEN)

    def test_ingest_and_night(self):
        d, p = self.day, self.prev
        lines = ["type|start|end|value|unit|source",
                 f"Sleep Analysis|{iso(p, 23)}|{iso(d, 2)}|Core||Ring",
                 f"Sleep Analysis|{iso(d, 2)}|{iso(d, 2, 10)}|Awake||Ring",
                 f"Sleep Analysis|{iso(d, 2, 10)}|{iso(d, 3)}|Deep||Ring",
                 f"Sleep Analysis|{iso(d, 3)}|{iso(d, 6, 30)}|REM||Ring",
                 f"Sleep Analysis|{iso(p, 22)}|{iso(d, 7)}|In Bed||iPhone",
                 f"Кислородна сатурация|{iso(d, 3)}|{iso(d, 3)}|0,96|%|Ring",
                 f"Heart Rate Variability|{iso(d, 4)}|{iso(d, 4)}|42|ms|Ring",
                 f"Steps|{iso(p, 10)}|{iso(p, 11)}|3000|count|iPhone",
                 f"Steps|{iso(p, 10)}|{iso(p, 11)}|2800|count|Ring",
                 f"Mystery|{iso(d, 4)}|{iso(d, 4)}|1||Ring",
                 "garbage line"]
        res = coach.ingest(self.con, "\n".join(lines))
        self.assertEqual(res, {"added": 10, "bad": 1})
        self.assertEqual(coach.ingest(self.con, "\n".join(lines))["added"], 0)  # idempotent
        n = coach.night(self.con, d)
        self.assertEqual((n["bed"], n["wake"], n["wakes"], n["deep_min"]), ("23:00", "06:30", 1, 50))
        self.assertAlmostEqual(n["asleep_h"], 7.33, places=2)
        self.assertEqual((n["spo2"], n["hrv"]), (96.0, 42.0))
        self.assertEqual(coach.steps(self.con, p), 3000)

    def test_grouped_total_is_replaced(self):
        p = self.prev
        line = f"Steps|{iso(p, 0)}|{iso(p, 24)}|{{}}|count|"
        coach.ingest(self.con, line.format(4000))
        self.assertEqual(coach.ingest(self.con, line.format(9500))["added"], 1)
        self.assertEqual(coach.steps(self.con, p), 9500)

    def test_json_ingest(self):
        body = json.dumps({"samples": [{"type": "Resting Heart Rate", "start": iso(self.day, 7), "end": iso(self.day, 7),
                                        "value": "55", "unit": "bpm", "source": "Ring"}]})
        self.assertEqual(coach.ingest(self.con, body)["added"], 1)
        self.assertEqual(coach.ingest(self.con, json.dumps({"data": "x|y|z|w"}))["bad"], 1)

    def test_readiness(self):
        base = {"asleep_h": 7, "wakes": 1, "hrv": 50, "rhr": 55, "spo2": 97, "resp": 14, "temp": 36.0}
        self.assertEqual(coach.readiness(dict(base), base)["level"], "green")
        self.assertEqual(coach.readiness({**base, "asleep_h": 5.5}, base)["level"], "yellow")
        self.assertEqual(coach.readiness({**base, "temp": 36.7, "rhr": 61}, base)["level"], "red")
        self.assertEqual(coach.readiness({"day": "x"}, base)["level"], "unknown")

    def test_validate(self):
        ok = coach.validate(plan(), self.day)
        self.assertEqual(ok["date"], self.day.isoformat())
        for bad in (plan(readiness="purple"), plan(items=[]), plan(evil=1),
                    plan(items=[{"id": "A B", "kind": "check", "label": "x"}]),
                    plan(items=[{"id": "a", "kind": "check", "label": "x", "xp": 500}]),
                    plan(recipe={"title": "x", "url": "javascript:alert(1)"})):
            with self.assertRaises(ValueError):
                coach.validate(bad, self.day)

    def test_plan_set_confined_to_work(self):
        f = Path(TMP, "plan.json")
        f.write_text(json.dumps(plan()))
        os.environ["DAILY_COACH_WORK"] = str(Path(TMP, "work"))
        try:
            with self.assertRaises(ValueError):
                coach.plan_set(self.con, f)
        finally:
            del os.environ["DAILY_COACH_WORK"]
        self.assertEqual(len(coach.plan_set(self.con, f)["items"]), 3)

    def store(self, day, p):
        self.con.execute("INSERT OR REPLACE INTO plans VALUES (?,?,0)", (day.isoformat(), json.dumps(coach.validate(p, day))))

    def test_xp_comeback_and_levels(self):
        d3, d2 = self.day - timedelta(days=3), self.day - timedelta(days=2)
        self.store(d3, plan())
        self.store(self.day, plan())
        self.con.execute("INSERT INTO checks VALUES (?,?,?,?,?,?,0)", (d3.isoformat(), "pushups", 1, None, None, None))
        res = coach.save_check(self.con, self.day, "pushups", done=True)
        self.assertTrue(res["today"]["showed_up"])
        h = {x["day"]: x for x in coach.history(self.con)}
        self.assertFalse(h[d3.isoformat()]["comeback"])
        self.assertTrue(h[self.day.isoformat()]["comeback"])  # d2 and yesterday had no plan
        self.assertEqual(res["xp"], 10 + 10 + coach.COMEBACK_XP)
        self.assertEqual(coach.level(0)["name"], "White")
        self.assertEqual(coach.level(100)["name"], "Yellow")
        self.assertEqual(coach.level(300)["name"], "Level 3")
        coach.save_check(self.con, self.day, "weight", value="81.4")
        self.assertEqual(coach.context(self.con)["measurements"]["weight_kg"][-1], [self.day.isoformat(), 81.4])
        with self.assertRaises(ValueError):
            coach.save_check(self.con, self.day, "nope", done=True)
        with self.assertRaises(ValueError):
            coach.save_check(self.con, d2, "pushups", done=True)  # no plan that day

    def test_email_and_pages_render(self):
        self.store(self.day, plan(recipe={"title": "Леща <b>", "url": "https://example.com/r", "time_min": 30}))
        self.con.commit()
        mail = coach.email(self.con)
        self.assertIn("[daily-coach]", mail["subject"])
        self.assertIn("Леща &lt;b&gt;", mail["html"])
        self.assertIn("10 push-ups", coach.today_page(self.con, self.day))
        self.assertIn("<svg", coach.dashboard(self.con, 14) + "<svg")


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = coach.ThreadingHTTPServer(("127.0.0.1", 0), coach.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def get(self, path, data=None):
        req = urllib.request.Request(self.base + path, data=data, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read().decode()

    def test_token_required(self):
        self.assertEqual(self.get("/")[0], 404)
        self.assertEqual(self.get("/wrong/")[0], 404)
        self.assertEqual(self.get(f"/{TOKEN}/")[0], 200)
        self.assertEqual(self.get(f"/{TOKEN}/dashboard")[0], 200)

    def test_ingest_endpoint(self):
        code, body = self.get(f"/{TOKEN}/ingest", b"Steps|2026-01-01T10:00:00+02:00|2026-01-01T11:00:00+02:00|5|count|x")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["bad"], 0)


class GuardTest(unittest.TestCase):
    def run_guard(self, tool, args, domains=("example.org",)):
        p = subprocess.run([sys.executable, "-I", str(HERE / "guard.py"), "/t", "/w", "me@example.com", *domains],
                           input=json.dumps({"tool_name": tool, "tool_input": args}), capture_output=True, text=True)
        return p.returncode

    def test_guard(self):
        g = "mcp__claude_ai_Gmail__"
        self.assertEqual(self.run_guard(g + "send_message", {"to": ["me@example.com"], "subject": "[daily-coach] x"}), 0)
        self.assertEqual(self.run_guard(g + "send_message", {"to": "evil@example.com", "subject": "[daily-coach] x"}), 2)
        self.assertEqual(self.run_guard(g + "send_message", {"to": "me@example.com", "subject": "hi"}), 2)
        self.assertEqual(self.run_guard(g + "send_message", {"to": "me@example.com", "subject": "[daily-coach]",
                                                            "draftId": "1"}), 2)
        self.assertEqual(self.run_guard(g + "search_threads", {"query": 'subject:"[daily-coach]" newer_than:4d'}), 0)
        self.assertEqual(self.run_guard(g + "search_threads", {"query": "bank"}), 2)
        self.assertEqual(self.run_guard(g + "search_threads", {"query": 'subject:"[daily-coach]" newer_than:4d OR bank'}), 2)
        self.assertEqual(self.run_guard("WebFetch", {"url": "https://www.example.org/recipe"}), 0)
        self.assertEqual(self.run_guard("WebFetch", {"url": "https://evil.example/?d=1"}), 2)
        self.assertEqual(self.run_guard("WebFetch", {"url": "https://example.org.evil.example/"}), 2)
        self.assertEqual(self.run_guard("WebFetch", {"url": "http://example.org/"}), 2)
        self.assertEqual(self.run_guard("WebFetch", {"url": "https://any.example/"}, domains=()), 0)
        self.assertEqual(self.run_guard(g + "create_draft", {}), 2)
        self.assertEqual(self.run_guard("Write", {"file_path": "/w/plan.json"}), 0)
        self.assertEqual(self.run_guard("Write", {"file_path": "/w/../etc/x"}), 2)
        self.assertEqual(self.run_guard("Edit", {"file_path": "/etc/profile"}), 2)
        self.assertEqual(self.run_guard("Bash", {"command": "/t/coach context"}), 0)
        self.assertEqual(self.run_guard("Bash", {"command": "/t/coach serve"}), 2)
        self.assertEqual(self.run_guard("Bash", {"command": "/t/coach context; rm -rf ~"}), 2)
        self.assertEqual(self.run_guard("Bash", {"command": "/t/coach email $(id)"}), 2)
        self.assertEqual(self.run_guard("Bash", {"command": "python3 -c 1"}), 2)


if __name__ == "__main__":
    unittest.main()
