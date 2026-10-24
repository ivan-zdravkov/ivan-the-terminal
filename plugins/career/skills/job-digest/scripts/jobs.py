#!/usr/bin/env python3
"""job-digest: stored digests and your marks on jobs in one SQLite file, plus the Jobs phone app. Stdlib only.

  jobs.py serve              HTTP server: the Jobs app (config: BIND, PORT)
  jobs.py url                print the app URL (it contains the secret token)
  jobs.py history            JSON for the run: jobs already listed, your marks with reasons, the last week's digests
  jobs.py digest-set FILE    validate and store a digest (FILE must be inside $JOB_DIGEST_WORK when set)
  jobs.py has-digest         exit 0 if today has a digest, 1 if not
  jobs.py notify             push "new digest" to every phone that turned notifications on
  jobs.py status             digests, marks, push devices

Config: ~/.config/ivan-the-terminal/job-digest/config.env (see ../config.example). Data: ~/.local/share/ivan-the-terminal/job-digest/
"""
import argparse
import hashlib
import html
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

HOME = Path.home()
CONF = Path(os.environ.get("JOB_DIGEST_CONF") or
            Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "ivan-the-terminal/job-digest/config.env")
DATA = Path(os.environ.get("JOB_DIGEST_DATA") or
            Path(os.environ.get("XDG_DATA_HOME", HOME / ".local/share")) / "ivan-the-terminal/job-digest")
_spec = importlib.util.spec_from_file_location("webapp", Path(__file__).resolve().parents[5] / "tools/webapp/webapp.py")
webapp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(webapp)
CFG = webapp.env(CONF, {"BIND": "127.0.0.1", "PORT": "8766", "TOKEN": "", "PUBLIC_URL": ""})
THEME, BG = "#2b5c8a", "#f6f5f1"
MARKS = {"applied": "Applied", "later": "Later", "no": "Not for me"}
TIERS = ("A", "B", "C")
RECRUITER_STATUS = {"drafted", "skipped", "labelled"}
# section -> (max entries, {field: max length}); url fields must be https
SECTIONS = {
    "needs_you": (10, {"title": 160, "why": 300, "url": 600, "due": 60}),
    "matches": (12, {"title": 160, "company": 100, "url": 600, "source": 40, "tier": 1, "why": 300, "engagement": 80,
                     "location": 120, "rate": 80, "posted": 30, "note": 1500, "contact": 200}),
    "outreach": (20, {"role": 160, "to": 120, "url": 600}),
    "apply_manually": (12, {"title": 160, "url": 600}),
    "recruiters": (40, {"who": 120, "subject": 200, "status": 12, "reason": 120, "url": 600}),
}
TEXTS = {"headline": 160, "weekly": 1500, "sources": 600}


# ---------------------------------------------------------------- store

def db():
    DATA.mkdir(parents=True, exist_ok=True)
    DATA.chmod(0o700)
    con = sqlite3.connect(DATA / "jobs.db", timeout=10)
    con.row_factory = sqlite3.Row
    con.executescript("""
      CREATE TABLE IF NOT EXISTS digests(id INTEGER PRIMARY KEY, day TEXT, at INTEGER, digest TEXT);
      CREATE TABLE IF NOT EXISTS marks(job TEXT PRIMARY KEY, mark TEXT, reason TEXT, at INTEGER);
      CREATE TABLE IF NOT EXISTS events(at INTEGER, kind TEXT, detail TEXT);
    """)
    return con


def token():
    return webapp.token(CFG["TOKEN"], DATA)


def push():
    return webapp.Push(DATA, CFG["PUBLIC_URL"] or "mailto:job-digest@localhost")


def jid(url):
    """Stable id for a posting: host + path (+ query without tracking params; LinkedIn ids live in the path)."""
    u = urlparse(url.strip())
    host = (u.hostname or "").lower().removeprefix("www.")
    query = "" if host.endswith("linkedin.com") else "&".join(
        sorted(p for p in u.query.split("&") if p and not re.match(r"(utm_|ref|trk|source|src)", p, re.I)))
    return hashlib.sha256(f"{host}{u.path.rstrip('/')}?{query}".encode()).hexdigest()[:12]


def clean(s, n):
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(s)).strip()[:n]


def validate(d, day):
    if not isinstance(d, dict):
        raise ValueError("digest must be a JSON object")
    unknown = set(d) - set(SECTIONS) - set(TEXTS) - {"date", "update", "failures"}
    if unknown:
        raise ValueError(f"unknown keys: {sorted(unknown)}")
    if d.get("date", day.isoformat()) != day.isoformat():
        raise ValueError(f"date must be {day.isoformat()}")
    out = {"date": day.isoformat(), "update": bool(d.get("update"))}
    for k, n in TEXTS.items():
        if d.get(k):
            out[k] = clean(d[k], n)
    for section, (limit, fields) in SECTIONS.items():
        items = d.get(section) or []
        if not isinstance(items, list) or len(items) > limit:
            raise ValueError(f"{section}: a list of at most {limit}")
        rows = []
        for i, it in enumerate(items):
            if not isinstance(it, dict) or set(it) - set(fields) - {"score", "flags"}:
                raise ValueError(f"{section}[{i}]: an object with only {sorted(fields)}")
            row = {k: clean(it[k], n) for k, n in fields.items() if it.get(k) not in (None, "")}
            if "url" in row and not row["url"].startswith("https://"):
                raise ValueError(f"{section}[{i}].url must start with https://")
            rows.append(row)
            if section != "matches":
                if section == "recruiters" and row.get("status") not in RECRUITER_STATUS:
                    raise ValueError(f"recruiters[{i}].status must be one of {sorted(RECRUITER_STATUS)}")
                if not (row.get("title") or row.get("role") or row.get("who")):
                    raise ValueError(f"{section}[{i}]: needs a title/role/who")
                continue
            if not row.get("title") or not row.get("url"):
                raise ValueError(f"matches[{i}]: title and an https url are required")
            if row.get("tier") not in TIERS:
                raise ValueError(f"matches[{i}].tier must be A, B or C")
            score = it.get("score")
            if not isinstance(score, int) or not 1 <= score <= 10:
                raise ValueError(f"matches[{i}].score must be an int 1-10")
            row["score"], row["id"] = score, jid(row["url"])
            flags = it.get("flags") or []
            if not isinstance(flags, list):
                raise ValueError(f"matches[{i}].flags must be a list")
            row["flags"] = [clean(f, 60) for f in flags[:4] if str(f).strip()]
        out[section] = rows
    fails = d.get("failures") or []
    if not isinstance(fails, list):
        raise ValueError("failures must be a list")
    out["failures"] = [clean(f, 200) for f in fails[:12]]
    return out


def digest_set(con, path):
    work = os.environ.get("JOB_DIGEST_WORK")
    p = Path(path).resolve()
    if work and Path(work).resolve() not in p.parents:
        raise ValueError(f"digest file must be inside {work}")
    day = date.today()
    d = validate(json.loads(p.read_text(encoding="utf-8")), day)
    con.execute("INSERT INTO digests(day, at, digest) VALUES (?,?,?)", (day.isoformat(), int(time.time()),
                                                                        json.dumps(d, ensure_ascii=False)))
    con.commit()
    return d


def digests(con, since):
    return [(r["day"], r["at"], json.loads(r["digest"])) for r in
            con.execute("SELECT day, at, digest FROM digests WHERE day>=? ORDER BY id", (since.isoformat(),))]


def known_jobs(con, days=180):
    """job id -> the newest listing of it (title, company, url, day)."""
    out = {}
    for day, _, d in digests(con, date.today() - timedelta(days=days)):
        for m in d.get("matches", []):
            out[m["id"]] = {"day": day, **{k: m.get(k, "") for k in ("title", "company", "url")}}
    return out


def marks(con):
    return {r["job"]: dict(r) for r in con.execute("SELECT * FROM marks")}


def set_mark(con, job, mark, reason=""):
    if not re.fullmatch(r"[0-9a-f]{12}", str(job)) or job not in known_jobs(con):
        raise ValueError("unknown job")
    if mark in ("", None):
        con.execute("DELETE FROM marks WHERE job=?", (job,))
    elif mark in MARKS:
        con.execute("INSERT OR REPLACE INTO marks VALUES (?,?,?,?)", (job, mark, clean(reason or "", 300), int(time.time())))
    else:
        raise ValueError(f"mark must be one of {sorted(MARKS)} or empty")
    con.commit()
    return {"job": job, "mark": mark or ""}


def history(con):
    """What the morning run needs to avoid repeats and learn from the marks."""
    t = date.today()
    listed = [[day, m.get("company", ""), m["title"], m["url"]]
              for day, _, d in digests(con, t - timedelta(days=45)) for m in d.get("matches", [])]
    jobs, out_marks = known_jobs(con), []
    for job, m in sorted(marks(con).items(), key=lambda kv: -kv[1]["at"]):
        if job in jobs and m["at"] >= time.time() - 120 * 86400:
            out_marks.append({"mark": m["mark"], "reason": m["reason"] or "",
                              "marked": datetime.fromtimestamp(m["at"]).date().isoformat(), **jobs[job]})
    week = [{"day": day, "at": datetime.fromtimestamp(at).strftime("%H:%M"), "update": d.get("update", False),
             "headline": d.get("headline", ""), "matches": len(d.get("matches", [])),
             "needs_you": [x.get("title", "") for x in d.get("needs_you", [])],
             "recruiters": [{k: x.get(k, "") for k in ("who", "subject", "status")} for x in d.get("recruiters", [])],
             "outreach": [{k: x.get(k, "") for k in ("role", "to")} for x in d.get("outreach", [])]}
            for day, at, d in digests(con, t - timedelta(days=7))]
    return {"today": t.isoformat(), "weekday": t.strftime("%A"),
            "digests_today": sum(1 for w in week if w["day"] == t.isoformat()),
            "already_listed": listed, "marks": out_marks, "last_7_days": week}


def day_view(con, day):
    """All digests of one day merged: an update adds to the morning digest instead of replacing it."""
    rows = [(at, d) for dd, at, d in digests(con, day) if dd == day.isoformat()]
    if not rows:
        return None
    view = {s: [] for s in SECTIONS}
    view.update(runs=[datetime.fromtimestamp(at).strftime("%H:%M") for at, _ in rows], failures=[])
    seen = set()
    for _, d in rows:
        for s in SECTIONS:
            for it in d.get(s, []):
                key = (s, it.get("id") or it.get("url") or json.dumps(it, sort_keys=True))
                if key not in seen:
                    seen.add(key)
                    view[s].append(it)
        for k in TEXTS:
            view[k] = d.get(k) or view.get(k, "")
        view["failures"] = d.get("failures", [])
    view["matches"].sort(key=lambda m: (TIERS.index(m["tier"]), -m["score"]))
    return view


def latest(con):
    r = con.execute("SELECT day FROM digests ORDER BY id DESC LIMIT 1").fetchone()
    v = day_view(con, date.fromisoformat(r[0])) if r else None
    if not v:
        return {"day": None, "title": "Jobs", "body": "No digest yet.", "url": ""}
    first = (v["needs_you"] or [{}])[0].get("title")
    m, o = len(v["matches"]), len(v["outreach"])
    return {"day": r[0], "title": f"💼 {m} match{'es' * (m != 1)} · {o} draft{'s' * (o != 1)}",
            "body": (f"Needs you: {first}. " if first else "") + v.get("headline", ""), "url": ""}


# ---------------------------------------------------------------- page

CSS = webapp.css(THEME, "#e8f0f8", "#7fb2e5", "#1d2a38") + """
.job.no{opacity:.55}.job .t{display:flex;justify-content:space-between;gap:8px;align-items:baseline}
.row{display:flex;gap:8px;margin-top:8px;flex-wrap:wrap}.flag{background:#f6e7c8;color:#5b4310}
@media (prefers-color-scheme:dark){.flag{background:#4a3b17;color:#f6e7c8}}
blockquote{margin:8px 0;padding:8px 12px;border-left:3px solid var(--acc);background:var(--bg);border-radius:6px;white-space:pre-wrap}
input[type=text]{font:inherit;padding:8px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg);flex:1}
summary{cursor:pointer;color:var(--acc);margin-top:6px}ul{padding-left:20px;margin:0}li{margin:6px 0}"""

JS = """async function post(p,b){const r=await fetch(p,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(b)});
const j=await r.json();if(!r.ok){alert(j.error||'failed');return null}return j}
document.querySelectorAll('.job').forEach(card=>{const job=card.dataset.job,why=card.querySelector('.why');
const show=m=>{card.classList.toggle('no',m==='no');card.querySelectorAll('[data-mark]').forEach(b=>b.classList.toggle('on',b.dataset.mark===m));card.dataset.mark=m};
card.querySelectorAll('[data-mark]').forEach(b=>b.addEventListener('click',async()=>{const m=card.dataset.mark===b.dataset.mark?'':b.dataset.mark;
if(m==='no'){why.hidden=false;why.querySelector('input').focus()}else why.hidden=true;if(await post('api/mark',{job,mark:m}))show(m)}));
why.querySelector('button').addEventListener('click',async()=>{if(await post('api/mark',{job,mark:'no',reason:why.querySelector('input').value})){why.hidden=true;show('no')}});
const c=card.querySelector('[data-copy]');if(c)c.addEventListener('click',()=>navigator.clipboard.writeText(card.querySelector('blockquote').textContent)
.then(()=>{c.textContent='Copied ✓'},()=>{c.textContent='Copy failed: select the text'}))});"""


@lru_cache(maxsize=1)
def vapid():
    try:
        return push().public_key()
    except (OSError, subprocess.SubprocessError):
        return ""


def page(title, body):
    return f"""<!doctype html><html lang="en"><head>{webapp.head("Jobs", THEME, vapid())}<title>{html.escape(title)}</title>
<style>{CSS}</style></head><body data-at="{datetime.now():%a %H:%M}"><main>{body}<p class=mute id=push></p></main>
<script>{JS}</script><script>{webapp.CLIENT_JS}</script></body></html>"""


def a(url, text):
    return f"<a href='{html.escape(url)}' rel='noopener noreferrer'>{html.escape(text)}</a>" if url else html.escape(text)


def job_html(m, mark):
    e = html.escape
    meta = " · ".join(e(m[k]) for k in ("company", "source", "posted") if m.get(k))
    terms = " · ".join(e(m[k]) for k in ("engagement", "location", "rate") if m.get(k))
    flags = "".join(f"<span class='pill flag'>{e(f)}</span> " for f in m.get("flags", []))
    note = (f"<details><summary>Application note</summary><blockquote>{e(m['note'])}</blockquote>"
            f"<button class=s data-copy>Copy</button></details>") if m.get("note") else ""
    btns = "".join(f"<button class='s{' on' if mark and mark['mark'] == k else ''}' data-mark={k}>{v}</button>"
                   for k, v in MARKS.items())
    reason = e(mark["reason"]) if mark and mark.get("reason") else ""
    return (f"<div class='card job{' no' if mark and mark['mark'] == 'no' else ''}' data-job={m['id']} "
            f"data-mark='{mark['mark'] if mark else ''}'><div class=t>{a(m['url'], m['title'])}"
            f"<span class=pill>{m['tier']} · {m['score']}/10</span></div><div class=mute>{meta}</div>"
            + (f"<div class=mute>{terms}</div>" if terms else "")
            + (f"<p style='margin:6px 0'>{e(m['why'])}</p>" if m.get("why") else "") + flags
            + (f"<div class=mute>{e(m['contact'])}</div>" if m.get("contact") else "") + note
            + f"<div class=row>{btns}</div><div class='row why' hidden><input type=text value='{reason}' "
            f"placeholder='Why not? Optional, it teaches the next run'><button>Save</button></div></div>")


def digest_page(con, day=None):
    e, t = html.escape, date.today()
    days = [r[0] for r in con.execute("SELECT DISTINCT day FROM digests ORDER BY day")]
    if not days:
        return page("Jobs", "<h1>Jobs</h1><div class=card>No digest yet. The first one lands after the next weekday run.</div>")
    shown = day.isoformat() if day and day.isoformat() in days else days[-1]
    v, i = day_view(con, date.fromisoformat(shown)), days.index(shown)
    nav = ("<nav>" + (f"<a href='?d={days[i - 1]}'>← {date.fromisoformat(days[i - 1]):%a %d}</a>" if i else "<span></span>")
           + (f"<a href='?d={days[i + 1]}'>{date.fromisoformat(days[i + 1]):%a %d} →</a>" if i + 1 < len(days)
              else "<a href='./'>Latest</a>" if shown != days[-1] else "<span></span>") + "</nav>")
    note = ""
    if day is None and shown != t.isoformat():
        note = (f"<div class=card>No digest today{' (weekend)' if t.weekday() >= 5 else ' yet'}: "
                f"this is {date.fromisoformat(shown):%A}’s.</div>")
    mk = marks(con)
    sec = []
    if v["needs_you"]:
        sec.append("<h2>Needs you today</h2><div class=card><ul>" + "".join(
            f"<li><b>{a(x.get('url', ''), x['title'])}</b>" + (f" · <span class=pill>{e(x['due'])}</span>" if x.get("due") else "")
            + (f"<div class=mute>{e(x['why'])}</div>" if x.get("why") else "") + "</li>" for x in v["needs_you"]) + "</ul></div>")
    sec.append("<h2>Top matches</h2>" + ("".join(job_html(m, mk.get(m["id"])) for m in v["matches"])
                                          or "<div class=card>No good matches today. That’s a valid result.</div>"))
    if v["outreach"]:
        sec.append("<h2>Drafts to send (attach the CV)</h2><div class=card><ul>" + "".join(
            f"<li>{a(x.get('url', ''), x.get('role', ''))} <span class=mute>→ {e(x.get('to', ''))}</span></li>"
            for x in v["outreach"]) + "</ul></div>")
    if v["apply_manually"]:
        sec.append("<h2>Apply on the platform</h2><div class=card><ul>" + "".join(
            f"<li>{a(x['url'], x['title'])}</li>" for x in v["apply_manually"]) + "</ul></div>")
    if v["recruiters"]:
        sec.append("<h2>Recruiter mail</h2><div class=card><ul>" + "".join(
            f"<li>{a(x.get('url', ''), x.get('who', ''))} <span class=pill>{e(x['status'])}</span>"
            + (f"<div class=mute>{e(x.get('subject', ''))}{' · ' + e(x['reason']) if x.get('reason') else ''}</div>")
            + "</li>" for x in v["recruiters"]) + "</ul></div>")
    if v.get("weekly"):
        sec.append(f"<h2>Weekly review</h2><div class=card style='white-space:pre-wrap'>{e(v['weekly'])}</div>")
    foot = (f"<p class=mute>Runs: {', '.join(v['runs'])}. {e(v.get('sources', ''))}"
            + "".join(f"<br>⚠ {e(f)}" for f in v["failures"]) + "</p>")
    body = (f"{nav}{note}<h1>{date.fromisoformat(shown):%A %d %b}</h1>"
            + (f"<div class=mute>{e(v['headline'])}</div>" if v.get("headline") else "") + "".join(sec) + foot)
    return page("Jobs", body)


# ---------------------------------------------------------------- server, CLI

class Handler(webapp.AppHandler):
    server_version = "job-digest"
    secret = staticmethod(lambda: token())

    def do_GET(self):
        rest, q = self.route()
        if rest is None:
            return self.send(404, "not found", "text/plain")
        if self.redirect_to_slash():
            return None
        con = db()
        try:
            if rest == []:
                return self.send(200, digest_page(con, date.fromisoformat(q["d"]) if "d" in q else None))
            if rest == ["api", "latest"]:
                return self.send(200, json.dumps(latest(con), ensure_ascii=False), "application/json")
            if rest == ["api", "ping"]:
                return self.send(200, "{}", "application/json")
            if rest == ["manifest.webmanifest"]:
                return self.send(200, webapp.manifest("Jobs", BG, THEME), "application/manifest+json")
            if len(rest) == 1 and (f := webapp.static(rest[0], THEME, "#ffffff", "case")):
                return self.send(200, *f)
            return self.send(404, "not found", "text/plain")
        except ValueError as ex:
            return self.send(400, str(ex), "text/plain")
        finally:
            con.close()

    def do_POST(self):
        rest, _ = self.route()
        if rest is None:
            return self.send(404, "not found", "text/plain")
        con = db()
        try:
            b = json.loads(self.body(100_000) or "{}")
            if rest == ["api", "mark"]:
                return self.send(200, json.dumps(set_mark(con, b.get("job"), b.get("mark"), b.get("reason"))), "application/json")
            if rest == ["api", "push"]:
                return self.send(200, json.dumps({"devices": push().subscribe(b)}), "application/json")
            return self.send(404, json.dumps({"error": "not found"}), "application/json")
        except (ValueError, KeyError, TypeError, AttributeError) as ex:
            return self.send(400, json.dumps({"error": str(ex)}), "application/json")
        finally:
            con.close()


def link(path=""):
    base = CFG["PUBLIC_URL"].rstrip("/")
    return f"{base}/{token()}/{path}" if base else ""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("digest-set").add_argument("file")
    for c in ("serve", "url", "history", "has-digest", "notify", "status"):
        sub.add_parser(c)
    args = ap.parse_args()
    if args.cmd == "serve":
        db().close()
        return webapp.serve("job-digest", Handler, CFG["BIND"], CFG["PORT"])
    if args.cmd == "url":
        if not CFG["PUBLIC_URL"]:
            sys.exit(f"job-digest: set PUBLIC_URL in {CONF}")
        return print(f"app: {link()}")
    con = db()
    try:
        if args.cmd == "history":
            print(json.dumps(history(con), ensure_ascii=False, separators=(",", ":")))
        elif args.cmd == "digest-set":
            d = digest_set(con, args.file)
            print(f"digest stored for {d['date']}: {len(d['matches'])} matches, {len(d['outreach'])} drafts, "
                  f"{len(d['recruiters'])} recruiter threads")
        elif args.cmd == "has-digest":
            sys.exit(0 if con.execute("SELECT 1 FROM digests WHERE day=?", (date.today().isoformat(),)).fetchone() else 1)
        elif args.cmd == "notify":
            sent, dropped = push().send()
            con.execute("INSERT INTO events VALUES (?,?,?)", (int(time.time()), "notify", f"sent={sent} dropped={dropped}"))
            con.commit()
            print(f"pushed to {sent} device(s), dropped {dropped} expired")
        elif args.cmd == "status":
            n = con.execute("SELECT count(*), max(day) FROM digests").fetchone()
            print(f"digests: {n[0]} stored, latest {n[1] or 'none'}")
            print("marks: " + ", ".join(f"{r[0]} {r[1]}" for r in con.execute("SELECT mark, count(*) FROM marks GROUP BY mark")))
            print(f"push: {len(push().subs())} device(s)")
    except (ValueError, json.JSONDecodeError, OSError) as ex:
        sys.exit(f"job-digest: {ex}")


if __name__ == "__main__":
    main()
