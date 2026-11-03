import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
TMP = tempfile.mkdtemp()
REPO = Path(TMP, "repo")
Path(TMP, "config.env").write_text(f'MAIL_TO="me@example.com"  # comment\nLEVEL_NAMES="White,Yellow"\n'
                                   f'WEB_DOMAINS="example.com"\n'
                                   f'HEALTH_REPO="{REPO.as_posix()}"\nHEALTH_REF="HEAD"\n')
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
        for t in ("samples", "plans", "checks", "events", "imported"):
            self.con.execute(f"DELETE FROM {t}")
        self.con.commit()
        self.day = coach.today()
        self.prev = self.day - timedelta(days=1)

    def tearDown(self):
        self.con.commit()
        self.con.close()

    def test_config_parsing(self):
        self.assertEqual(coach.CFG["MAIL_TO"], "me@example.com")
        self.assertEqual(coach.CFG["HEALTH_DIR"], "health")

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
                    plan(recipe={"title": "x", "url": "javascript:alert(1)"}),
                    plan(recipe={"title": "x", "url": "https://evil.example/r?d=secret"}),  # not a WEB_DOMAINS site
                    plan(recipe={"title": "x", "url": "https://example.com.evil.example/r"}),
                    plan(tip="see https://evil.example/?d=1"), plan(headline="evil.example/x"),
                    plan(why="go to www.evil"),
                    plan(items=[{"id": "a", "kind": "check", "label": "visit evil.example", "xp": 1}]),
                    plan(recipe={"title": "x", "url": "https://www.example.com/r", "shopping": ["evil.example"]})):
            with self.assertRaises(ValueError, msg=repr(bad)[:120]):
                coach.validate(bad, self.day)
        self.assertEqual(coach.validate(plan(tip="e.g. 10 min, 3.5 kg, a.m. walk", recipe={
            "title": "Леща", "url": "https://www.example.com/r"}), self.day)["recipe"]["url"], "https://www.example.com/r")

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

    def test_email_renders_and_escapes(self):
        self.store(self.day, plan(recipe={"title": "Леща <b>", "url": "https://example.com/r", "time_min": 30,
                                          "shopping": ["лук"]}))
        self.con.commit()
        coach.save_check(self.con, self.day, "pushups", done=True)
        m = coach.email(self.con)
        self.assertEqual(m["to"], "me@example.com")
        self.assertTrue(m["subject"].startswith(f"Daily plan {self.day.isoformat()}: 🟢 Go"))
        self.assertIn("Леща &lt;b&gt;", m["html"])
        self.assertNotIn("<b>Леща <b>", m["html"])
        self.assertIn("☑ ★ 10 push-ups", m["text"])
        self.assertIn("☐ Weight: ___", m["text"])
        self.assertIn("https://example.com/r", m["text"])
        with self.assertRaises(ValueError):
            coach.email(self.con, self.day - timedelta(days=5))  # no plan that day

    def test_checks_set_from_replies(self):
        self.store(self.prev, plan())
        self.con.commit()
        work = Path(TMP, "work")
        work.mkdir(exist_ok=True)
        f = work / "checks.json"
        f.write_text(json.dumps([{"day": self.prev.isoformat(), "id": "pushups", "done": True},
                                 {"day": self.prev.isoformat(), "id": "weight", "value": 91.8},
                                 {"day": self.prev.isoformat(), "id": "nope", "done": True}]), encoding="utf-8")
        os.environ["DAILY_COACH_WORK"] = str(work)
        try:
            res = coach.checks_set(self.con, f)
            outside = Path(TMP, "checks.json")
            outside.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                coach.checks_set(self.con, outside)
        finally:
            del os.environ["DAILY_COACH_WORK"]
        self.assertEqual(res["stored"], 2)
        self.assertEqual(len(res["errors"]), 1)
        self.assertEqual(res["xp"], 15)

    def test_import_from_the_repo(self):
        def git(*args):
            subprocess.run(["git", "-C", str(REPO), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                           check=True, capture_output=True)
        REPO.mkdir(exist_ok=True)
        git("init", "-q")
        d = self.day
        Path(REPO, "health/2026/11").mkdir(parents=True, exist_ok=True)
        Path(REPO, "health/2026/11/a.txt").write_text(f"Steps|{iso(d, 10)}|{iso(d, 11)}|500|count|Ring\n",
                                                      encoding="utf-8")
        Path(REPO, "notes.txt").write_text(f"Steps|{iso(d, 12)}|{iso(d, 13)}|9|count|Ring\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", "x")
        res = coach.import_repo(self.con, do_fetch=False)
        self.assertEqual((res["files"], res["added"], res["bad"]), (1, 1, 0))  # only files under HEALTH_DIR
        self.assertEqual(coach.import_repo(self.con, do_fetch=False)["files"], 0)  # never twice
        Path(REPO, "health/2026/11/b.txt").write_text("garbage\n", encoding="utf-8")
        Path(REPO, "health/2026/11/c.txt").write_text("not committed yet\n", encoding="utf-8")
        git("add", "health/2026/11/b.txt")
        git("commit", "-q", "-m", "y")
        res = coach.import_repo(self.con, do_fetch=False)
        self.assertEqual((res["files"], res["bad"]), (1, 1))  # reads the ref, not the working tree
        self.assertEqual(coach.steps(self.con, d), 500)

    def test_health_repo_relative_to_the_config(self):
        self.assertEqual(coach.health_repo(), REPO)
        old = coach.CFG["HEALTH_REPO"]
        self.addCleanup(coach.CFG.__setitem__, "HEALTH_REPO", old)
        coach.CFG["HEALTH_REPO"] = "repo"
        self.assertEqual(coach.health_repo(), Path(TMP).resolve() / "repo")
        coach.CFG["HEALTH_REPO"] = ""
        with self.assertRaises(ValueError):
            coach.health_repo()

    def test_night_over_starts_the_plan_after_waking(self):
        d, p = self.day, self.prev
        coach.ingest(self.con, f"Sleep Analysis|{iso(p, 23)}|{iso(d, 6, 30)}|Core||Ring\n"
                               f"Sleep Analysis|{iso(d, 6, 30)}|{iso(d, 9)}|In Bed||iPhone")
        wake = datetime.fromisoformat(iso(d, 6, 30)).timestamp()
        self.assertFalse(coach.night_over(self.con, wake + 5 * 60))   # maybe just a toilet trip
        self.assertTrue(coach.night_over(self.con, wake + 25 * 60))   # in-bed time doesn't count as sleep
        self.assertFalse(coach.night_over(self.con, datetime.fromisoformat(iso(d, 5, 59)).timestamp()))  # too early
        self.con.execute("DELETE FROM samples")
        self.assertFalse(coach.night_over(self.con, wake + 25 * 60))  # no ring data: the fallback timer decides


class GuardTest(unittest.TestCase):
    def run_guard(self, tool, args, domains=("example.org",), tools="/t"):
        p = subprocess.run([sys.executable, "-I", str(HERE / "guard.py"), tools, "/w", "me@example.com", *domains],
                           input=json.dumps({"tool_name": tool, "tool_input": args}), capture_output=True, text=True,
                           encoding="utf-8")
        return p.returncode

    def test_send_is_pinned_to_the_rendered_email(self):
        con = coach.db()
        day = coach.today()
        con.execute("INSERT OR REPLACE INTO plans VALUES (?,?,0)", (day.isoformat(), json.dumps(coach.validate(plan(), day))))
        con.commit()
        mail = coach.email(con)
        con.close()
        g, T = "mcp__claude_ai_Gmail__send_message", HERE.as_posix()
        ok = {"to": ["me@example.com"], "subject": mail["subject"], "htmlBody": mail["html"], "body": mail["text"]}
        self.assertEqual(self.run_guard(g, ok, tools=T), 0)
        self.assertEqual(self.run_guard(g, {**ok, "to": "me@example.com"}, tools=T), 0)
        self.assertEqual(self.run_guard(g, {**ok, "htmlBody": mail["html"].replace("\n", "\n  ")}, tools=T), 0)  # spacing
        for bad in ({**ok, "htmlBody": mail["html"] + "<img src='https://evil.example/?d=1'>"},
                    {**ok, "body": mail["text"] + " https://evil.example/?d=1"}, {**ok, "subject": "Daily plan x"},
                    {**ok, "to": ["Me <me@example.com>"]}, {**ok, "to": ["x@example.org"]},
                    {**ok, "to": ["me@example.com", "x@example.org"]}, {**ok, "bcc": ["x@example.org"]},
                    {**ok, "replyToMessageId": "m1"}, {"draftId": "r1"}):
            self.assertEqual(self.run_guard(g, bad, tools=T), 2, repr(bad)[:100])
        self.assertEqual(self.run_guard(g, ok, tools="/t"), 2)  # can't render: fail closed

    def test_guard(self):
        g = "mcp__claude_ai_Gmail__"
        self.assertEqual(self.run_guard(g + "search_threads", {"query": 'subject:"Daily plan" from:me newer_than:8d'}), 0)
        self.assertEqual(self.run_guard(g + "search_threads", {"query": 'subject:"Daily plan" newer_than:8d'}), 2)
        self.assertEqual(self.run_guard(g + "search_threads", {"query": "verification code"}), 2)
        self.assertEqual(self.run_guard(g + "get_thread", {"threadId": "t1"}), 0)
        self.assertEqual(self.run_guard(g + "get_message", {"messageId": "m1"}), 2)
        self.assertEqual(self.run_guard("WebFetch", {"url": "https://example.org/"}, domains=()), 2)  # fail closed
        for tool in ("create_draft", "reply", "forward", "unlabel_thread", "trash_thread", "label_thread"):
            self.assertEqual(self.run_guard(g + tool, {}), 2, tool)
        self.assertEqual(self.run_guard("mcp__other__anything", {}), 2)
        self.assertEqual(self.run_guard("PowerShell", {"command": "Get-Date"}), 2)
        self.assertEqual(self.run_guard("Monitor", {"command": "date"}), 2)
        self.assertEqual(self.run_guard("WebFetch", {"url": "https://www.example.org/recipe"}), 0)
        self.assertEqual(self.run_guard("WebFetch", {"url": "https://evil.example/?d=1"}), 2)
        self.assertEqual(self.run_guard("WebFetch", {"url": "https://example.org.evil.example/"}), 2)
        self.assertEqual(self.run_guard("WebFetch", {"url": "http://example.org/"}), 2)
        self.assertEqual(self.run_guard("Write", {"file_path": "/w/plan.json"}), 0)
        self.assertEqual(self.run_guard("Write", {"file_path": "/w/../etc/x"}), 2)
        self.assertEqual(self.run_guard("Edit", {"file_path": "/etc/profile"}), 2)
        for sub_ in ("context", "checks-set /w/checks.json", "plan-set /w/plan.json", "email", "has-plan", "status"):
            self.assertEqual(self.run_guard("Bash", {"command": f"/t/coach.py {sub_}"}), 0, sub_)
        for sub_ in ("import", "ready", "ingest /etc/passwd", "serve"):
            self.assertEqual(self.run_guard("Bash", {"command": f"/t/coach.py {sub_}"}), 2, sub_)
        self.assertEqual(self.run_guard("Bash", {"command": "/t/coach context"}), 2)  # pre-.py name
        self.assertEqual(self.run_guard("Bash", {"command": "/t/coach.py context; rm -rf ~"}), 2)
        self.assertEqual(self.run_guard("Bash", {"command": "date +%F"}), 0)
        for cmd in ("date $'\\'' ; id ; echo #'", "date -f /etc/passwd", "date --file=/etc/passwd", "date -r /etc/passwd"):
            self.assertEqual(self.run_guard("Bash", {"command": cmd}), 2, cmd)
        self.assertEqual(self.run_guard("Bash", {"command": "/t/coach.py status#;/t/coach.py url"}), 2)  # mid-word '#'
        self.assertEqual(self.run_guard("Bash", {"command": "/t/coach.py status $(id)"}), 2)
        self.assertEqual(self.run_guard("Bash", {"command": "python3 -c 1"}), 2)


if __name__ == "__main__":
    unittest.main()
