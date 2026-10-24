"""Tests for the job-digest store, digest validation, marks and the Jobs app server."""
import importlib.util
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
TMP = tempfile.mkdtemp()
TOKEN = "j" * 20
Path(TMP, "config.env").write_text(f'TOKEN="{TOKEN}"\nPORT=0\n')
os.environ.update(JOB_DIGEST_CONF=str(Path(TMP, "config.env")), JOB_DIGEST_DATA=TMP)
spec = importlib.util.spec_from_file_location("jobs", HERE / "jobs.py")
jobs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jobs)


def match(n, **kw):
    return {"title": f"Backend dev {n}", "company": "Acme", "url": f"https://jobs.example.com/{n}?utm_source=x",
            "tier": "B", "score": 7, "note": "I build <b>APIs</b>.", **kw}


def digest(**kw):
    return {"headline": "2 matches", "matches": [match(1), match(2, tier="A", score=6)],
            "needs_you": [{"title": "Proxify test", "url": "https://mail.google.com/mail/u/0/#all/abc", "due": "17:00"}],
            "recruiters": [{"who": "Jane", "status": "drafted", "url": "https://mail.google.com/mail/u/0/#all/def"}], **kw}


class Store(unittest.TestCase):
    def setUp(self):
        self.con = jobs.db()
        for t in ("digests", "marks", "events"):
            self.con.execute(f"DELETE FROM {t}")
        self.con.commit()
        self.work = Path(TMP, "work")
        self.work.mkdir(exist_ok=True)
        os.environ["JOB_DIGEST_WORK"] = str(self.work)

    def tearDown(self):
        os.environ.pop("JOB_DIGEST_WORK", None)
        self.con.close()

    def put(self, d, name="digest.json"):
        f = self.work / name
        f.write_text(json.dumps(d))
        return jobs.digest_set(self.con, f)

    def test_job_ids_ignore_tracking(self):
        self.assertEqual(jobs.jid("https://www.example.com/j/1/?utm_source=a&ref=b"), jobs.jid("https://example.com/j/1"))
        self.assertEqual(jobs.jid("https://www.linkedin.com/jobs/view/42/?trk=x&refId=y"),
                         jobs.jid("https://linkedin.com/jobs/view/42"))
        self.assertNotEqual(jobs.jid("https://example.com/j?id=1"), jobs.jid("https://example.com/j?id=2"))

    def test_validate_rejects_bad_digests(self):
        t = date.today()
        for bad in (digest(evil=1), digest(date="2001-01-01"), digest(matches=[match(1, url="javascript:alert(1)")]),
                    digest(matches=[match(1, tier="Z")]), digest(matches=[match(1, score=11)]),
                    digest(matches=[match(1, score="9")]), digest(matches=[match(1, extra=1)]),
                    digest(recruiters=[{"who": "x", "status": "sent"}]), digest(needs_you=[{"url": "https://x.example"}]),
                    digest(matches=[match(i) for i in range(13)]), digest(needs_you="x")):
            with self.assertRaises(ValueError):
                jobs.validate(bad, t)

    def test_digest_set_confined_to_work(self):
        outside = Path(TMP, "outside.json")
        outside.write_text(json.dumps(digest()))
        with self.assertRaises(ValueError):
            jobs.digest_set(self.con, outside)
        self.assertEqual(len(self.put(digest())["matches"]), 2)

    def test_day_view_merges_updates_and_ranks(self):
        self.put(digest())
        self.put(digest(update=True, headline="", matches=[match(1), match(3, tier="A", score=9)], needs_you=[]))
        v = jobs.day_view(self.con, date.today())
        self.assertEqual([m["title"][-1] for m in v["matches"]], ["3", "2", "1"])  # A9, A6, B7; no duplicate of 1
        self.assertEqual(v["headline"], "2 matches")
        self.assertEqual(len(v["runs"]), 2)
        self.assertEqual(len(v["needs_you"]), 1)

    def test_marks_and_history(self):
        d = self.put(digest())
        jid = d["matches"][0]["id"]
        jobs.set_mark(self.con, jid, "no", "too junior")
        with self.assertRaises(ValueError):
            jobs.set_mark(self.con, "0" * 12, "no")
        with self.assertRaises(ValueError):
            jobs.set_mark(self.con, jid, "maybe")
        h = jobs.history(self.con)
        self.assertEqual(h["digests_today"], 1)
        self.assertEqual(len(h["already_listed"]), 2)
        self.assertEqual((h["marks"][0]["mark"], h["marks"][0]["reason"], h["marks"][0]["title"]),
                         ("no", "too junior", "Backend dev 1"))
        jobs.set_mark(self.con, jid, "")
        self.assertEqual(jobs.history(self.con)["marks"], [])

    def test_page_escapes_and_shows_latest(self):
        self.assertIn("No digest yet", jobs.digest_page(self.con))
        self.put(digest(matches=[match(1, title="<script>x</script>")]))
        old = (date.today() - timedelta(days=3)).isoformat()
        self.con.execute("UPDATE digests SET day=?", (old,))
        self.con.commit()
        page = jobs.digest_page(self.con)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("<script>x", page)
        self.assertIn("No digest today", page)  # shows the newest earlier day, and says so
        self.assertIn("I build &lt;b&gt;APIs&lt;/b&gt;.", page)
        self.assertEqual(jobs.latest(self.con)["day"], old)


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), jobs.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def req(self, path, data=None):
        r = urllib.request.Request(self.base + path, data=json.dumps(data).encode() if data is not None else None,
                                   method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, resp.read().decode(errors="replace")
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read().decode()

    def test_token_and_routes(self):
        self.assertEqual(self.req("/")[0], 404)
        self.assertEqual(self.req("/nope/")[0], 404)
        for path in ("", "manifest.webmanifest", "sw.js", "icon-192.png", "api/latest", "api/ping"):
            self.assertEqual(self.req(f"/{TOKEN}/{path}")[0], 200, path)

    def test_mark_endpoint_validates(self):
        self.assertEqual(self.req(f"/{TOKEN}/api/mark", {"job": "abc", "mark": "no"})[0], 400)
        self.assertEqual(self.req(f"/{TOKEN}/api/push", {"endpoint": "https://evil.example/x"})[0], 400)


if __name__ == "__main__":
    unittest.main()
