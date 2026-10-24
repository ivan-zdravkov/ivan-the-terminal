#!/usr/bin/env python3
"""daily-coach: health samples, daily plans and check-ins in one SQLite file, plus the phone app. Stdlib only.

  coach.py serve                 HTTP server: the Daily app (check-in, trends), /ingest for the phone (config: BIND, PORT)
  coach.py url                   print the app and ingest URLs (they contain the secret token)
  coach.py ingest FILE           store samples from a file (same format as POST /ingest)
  coach.py context [--days N]    JSON for the morning run: nights, vitals vs baseline, readiness, check-ins, XP
  coach.py plan-set FILE         validate and store today's plan (FILE must be inside $DAILY_COACH_WORK when set)
  coach.py notify                push "today's plan is ready" to every phone that turned notifications on
  coach.py has-plan              exit 0 if today has a plan, 1 if not
  coach.py status                last sync, metrics seen, unknown sample types, today's plan, XP, push devices

Config: ~/.config/ivan-the-terminal/daily-coach/config.env (see ../config.example). Data: ~/.local/share/ivan-the-terminal/daily-coach/
"""
import argparse
import html
import importlib.util
import json
import math
import os
import re
import shlex
import sqlite3
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

HOME = Path.home()
CONF = Path(os.environ.get("DAILY_COACH_CONF") or
            Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "ivan-the-terminal/daily-coach/config.env")
DATA = Path(os.environ.get("DAILY_COACH_DATA") or
            Path(os.environ.get("XDG_DATA_HOME", HOME / ".local/share")) / "ivan-the-terminal/daily-coach")
DEFAULTS = {"BIND": "127.0.0.1", "PORT": "8765", "TOKEN": "", "PUBLIC_URL": "", "DAY_START_HOUR": "4",
            "AUTO_PLAN_HOUR": "6", "LEVEL_NAMES": "", "TRIGGER": "systemctl --user start --no-block daily-coach.service"}
_spec = importlib.util.spec_from_file_location("webapp", Path(__file__).resolve().parents[5] / "tools/webapp/webapp.py")
webapp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(webapp)
THEME, BG = "#2f6f4f", "#f6f5f1"

# Health sample type names (English and Bulgarian iPhone locales) -> metric. Order matters: specific before generic.
METRICS = [
    ("sleep", ("sleep", "сън", "съня")),
    ("rhr", ("resting heart", "в покой")),
    ("hrv", ("variability", "вариабилност")),
    ("hr", ("heart rate", "сърдечен ритъм", "пулс")),
    ("spo2", ("oxygen", "кислород")),
    ("resp", ("respiratory", "дихател")),
    ("temp", ("temperature", "температура")),
    ("steps", ("step", "стъпки")),
    ("active_kcal", ("active energy", "активна енергия")),
    ("weight", ("body mass", "weight", "тегло")),
]
STAGES = [("deep", r"deep|дълб"), ("rem", r"\brem\b"), ("core", r"core|light|основ|лек"), ("awake", r"awake|буд"),
          ("inbed", r"in ?bed|легло"), ("asleep", r"asleep|sleep|спи|сън|заспал")]
SLEEP_ENUM = {0: "inbed", 1: "asleep", 2: "awake", 3: "core", 4: "deep", 5: "rem"}  # HKCategoryValueSleepAnalysis
ASLEEP = ("core", "deep", "rem", "asleep")
KINDS = {"check", "number", "scale", "text"}
READINESS = {"green": "🟢", "yellow": "🟡", "red": "🔴", "unknown": "⚪"}
COMEBACK_XP = 20


# ---------------------------------------------------------------- config, db, time

def config():
    return webapp.env(CONF, DEFAULTS)


CFG = config()


def db():
    DATA.mkdir(parents=True, exist_ok=True)
    DATA.chmod(0o700)  # health data: owner only
    con = sqlite3.connect(DATA / "coach.db", timeout=10)
    con.row_factory = sqlite3.Row
    con.executescript("""
      CREATE TABLE IF NOT EXISTS samples(k TEXT PRIMARY KEY, metric TEXT, raw TEXT, start INTEGER, end INTEGER,
        value REAL, text TEXT, unit TEXT, source TEXT);
      CREATE INDEX IF NOT EXISTS samples_metric ON samples(metric, start);
      CREATE TABLE IF NOT EXISTS plans(day TEXT PRIMARY KEY, plan TEXT, created INTEGER);
      CREATE TABLE IF NOT EXISTS checks(day TEXT, item TEXT, done INTEGER, value REAL, text TEXT, metric TEXT,
        at INTEGER, PRIMARY KEY(day, item));
      CREATE TABLE IF NOT EXISTS events(at INTEGER, kind TEXT, detail TEXT);
    """)
    return con


def token():
    """Secret path prefix for every URL. From config, else generated once into the data dir (outside any repo)."""
    return webapp.token(CFG["TOKEN"], DATA)


def today():
    return (datetime.now() - timedelta(hours=int(CFG["DAY_START_HOUR"]))).date()


def at(day, hour):
    return int(datetime(day.year, day.month, day.day).timestamp() + hour * 3600)


def hm(ts):
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def rnd(x, n=1):
    return None if x is None else round(x, n)


# ---------------------------------------------------------------- ingest

def metric_of(raw):
    low = raw.strip().lower()
    for metric, keys in METRICS:
        if any(k in low for k in keys):
            return metric
    return "raw:" + low[:40]


def stage_of(text):
    t = (text or "").strip().lower()
    if re.fullmatch(r"\d", t):
        return SLEEP_ENUM.get(int(t))
    for stage, pattern in STAGES:
        if re.search(pattern, t):
            return stage
    return None


TIME_FORMATS = ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M %z", "%d.%m.%Y, %H:%M", "%d.%m.%Y %H:%M", "%d.%m.%Y г., %H:%M",
                "%b %d, %Y at %I:%M %p", "%d %b %Y at %H:%M", "%m/%d/%Y, %I:%M %p")


def parse_time(s):
    s = s.strip().replace(" ", " ")
    try:
        return int(datetime.fromisoformat(s).timestamp())
    except ValueError:
        pass
    for fmt in TIME_FORMATS:
        try:
            return int(datetime.strptime(s, fmt).timestamp())
        except ValueError:
            continue
    return None


def parse_value(s):
    m = re.match(r"^\s*(-?\d+(?:[.,]\d+)?)\s*(\S.*)?$", s or "")
    if not m:
        return None, (s or "").strip()
    return float(m.group(1).replace(",", ".")), ""


def rows_from_body(body):
    """Accept 'type|start|end|value|unit|source' lines, or JSON {samples: [{type,start,end,value,unit,source}]}
    or {data|text|csv: '<lines>'}."""
    text = body.strip()
    if text[:1] in "{[":
        data = json.loads(text)
        if isinstance(data, dict):
            for key in ("data", "text", "csv", "lines"):
                if isinstance(data.get(key), str):
                    return rows_from_body(data[key])
            data = data.get("samples", [])
        return [[str(r.get(k, "")) for k in ("type", "start", "end", "value", "unit", "source")]
                for r in data if isinstance(r, dict)]
    return [[p.strip() for p in line.split("|")] for line in text.splitlines() if line.strip()]


def ingest(con, body):
    added = bad = 0
    for parts in rows_from_body(body):
        if parts[0].lower() == "type":  # header line
            continue
        if len(parts) < 4:
            bad += 1
            continue
        raw, start, end, value = parts[:4]
        unit, source = (parts + ["", ""])[4:6]
        t0, t1 = parse_time(start), parse_time(end) or parse_time(start)
        if t0 is None:
            bad += 1
            continue
        metric = metric_of(raw)
        num, txt = parse_value(value)
        if metric == "sleep":
            txt, num = stage_of(value) or txt or value, None
        elif metric == "spo2" and num is not None and num <= 1:
            num *= 100
        elif metric == "temp" and num is not None and num > 50:
            num = (num - 32) * 5 / 9
        if metric != "sleep" and num is None and not metric.startswith("raw:"):
            bad += 1
            continue
        # Same metric, interval and source = same sample; a new value (a day's step total growing) replaces it.
        k = f"{metric}|{t0}|{t1}|{source}" + (f"|{txt}" if metric == "sleep" or num is None else "")
        old = con.execute("SELECT value, text FROM samples WHERE k=?", (k,)).fetchone()
        if old and (old[0], old[1]) == (num, txt[:40]):
            continue
        con.execute("INSERT OR REPLACE INTO samples VALUES (?,?,?,?,?,?,?,?,?)",
                    (k, metric, raw[:80], t0, t1, num, txt[:40], unit[:20], source[:60]))
        added += 1
    con.execute("INSERT INTO events VALUES (?,?,?)", (int(time.time()), "ingest", f"added={added} bad={bad}"))
    con.commit()
    return {"added": added, "bad": bad}


# ---------------------------------------------------------------- summaries

def union(intervals):
    out = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def secs(intervals):
    return sum(b - a for a, b in union(intervals))


def night(con, day):
    """Sleep for the night that ends on `day` (18:00 the evening before .. 14:00), from the best-staged source."""
    rows = con.execute("SELECT start, end, text, source FROM samples WHERE metric='sleep' AND end>? AND start<?",
                       (at(day - timedelta(days=1), 18), at(day, 14))).fetchall()
    out = {"day": day.isoformat()}
    by_src = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by_src[r["source"]][r["text"]].append((r["start"], r["end"]))
    if by_src:
        def rank(src):
            st = by_src[src]
            return (sum(secs(st[s]) for s in ("core", "deep", "rem")), sum(secs(st[s]) for s in ASLEEP))
        st = by_src[max(by_src, key=rank)]
        sleep = union([iv for s in ASLEEP for iv in st[s]])
        if sleep:
            bed, wake = sleep[0][0], sleep[-1][1]
            asleep = secs(sleep)
            out.update(bed=hm(bed), wake=hm(wake), asleep_h=rnd(asleep / 3600, 2),
                       deep_min=round(secs(st["deep"]) / 60), rem_min=round(secs(st["rem"]) / 60),
                       awake_min=round((wake - bed - asleep) / 60),
                       wakes=sum(1 for x, y in zip(sleep, sleep[1:]) if y[0] - x[1] >= 180),
                       eff=round(100 * asleep / max(wake - bed, 1)), _win=(bed, wake))
    lo, hi = out.pop("_win", (at(day - timedelta(days=1), 22), at(day, 8)))

    def vals(metric, a=lo, b=hi):
        return [r[0] for r in con.execute("SELECT value FROM samples WHERE metric=? AND start>=? AND start<? "
                                          "AND value IS NOT NULL", (metric, a, b))]
    day_lo, day_hi = at(day, 0), at(day, 24)
    hr, hrv, spo2 = vals("hr"), vals("hrv") or vals("hrv", day_lo, day_hi), vals("spo2")
    rhr = vals("rhr", day_lo, day_hi)
    temp = vals("temp") or vals("temp", day_lo, day_hi)
    resp = vals("resp")
    out.update(hrv=rnd(statistics.mean(hrv)) if hrv else None,
               rhr=rnd(rhr[-1]) if rhr else (rnd(sorted(hr)[len(hr) // 10]) if len(hr) >= 5 else None),
               spo2=rnd(statistics.mean(spo2)) if spo2 else None, spo2_min=rnd(min(spo2)) if spo2 else None,
               resp=rnd(statistics.mean(resp)) if resp else None, temp=rnd(statistics.mean(temp), 2) if temp else None)
    return out


def steps(con, day):
    per_src = defaultdict(float)
    for r in con.execute("SELECT value, source FROM samples WHERE metric='steps' AND start>=? AND start<?",
                         (at(day, 0), at(day, 24))):
        per_src[r["source"]] += r["value"] or 0
    return round(max(per_src.values())) if per_src else None  # sources overlap (phone + ring): take the larger


BASE_KEYS = ("asleep_h", "wakes", "hrv", "rhr", "spo2", "resp", "temp")


def baselines(nights):
    out = {}
    for k in BASE_KEYS:
        vs = [n[k] for n in nights if n.get(k) is not None]
        out[k] = rnd(statistics.median(vs), 2) if len(vs) >= 5 else None
    return out


def readiness(n, base):
    """Deterministic first guess; the morning run may downgrade it from Ivan's notes."""
    if not n or all(n.get(k) is None for k in BASE_KEYS):
        return {"level": "unknown", "flags": ["no ring data for last night"]}
    flags, sick = [], 0

    def d(k):
        return None if n.get(k) is None or base.get(k) is None else n[k] - base[k]
    if (x := d("temp")) is not None and x >= 0.5:
        flags.append(f"temperature +{x:.1f}°C vs baseline")
        sick += 2
    if (x := d("rhr")) is not None and x >= 5:
        flags.append(f"resting HR +{x:.0f} bpm vs baseline")
        sick += 1
    if n.get("hrv") and base.get("hrv") and n["hrv"] <= 0.8 * base["hrv"]:
        flags.append(f"HRV {n['hrv']:.0f} ms vs baseline {base['hrv']:.0f}")
        sick += 1
    if (x := d("resp")) is not None and x >= 2:
        flags.append(f"breathing rate +{x:.1f}/min vs baseline")
        sick += 1
    if n.get("spo2") is not None and (n["spo2"] < 94 or (base.get("spo2") and n["spo2"] <= base["spo2"] - 2)):
        flags.append(f"SpO2 avg {n['spo2']:.0f}% (min {n.get('spo2_min')})")
    if n.get("asleep_h") is not None and n["asleep_h"] < 6:
        flags.append(f"short sleep {n['asleep_h']:.1f} h")
    if (n.get("wakes") or 0) >= 4 or (n.get("eff") or 100) < 80:
        flags.append(f"fragmented: {n.get('wakes')} wake-ups, efficiency {n.get('eff')}%")
    level = "red" if sick >= 2 or (n.get("asleep_h") or 9) < 4.5 else "yellow" if flags else "green"
    return {"level": level, "flags": flags, "illness_signals": sick}


# ---------------------------------------------------------------- plans, check-ins, XP

def plan_of(con, day):
    r = con.execute("SELECT plan FROM plans WHERE day=?", (day.isoformat(),)).fetchone()
    return json.loads(r[0]) if r else None


def checks_of(con, day):
    return {r["item"]: dict(r) for r in con.execute("SELECT * FROM checks WHERE day=?", (day.isoformat(),))}


def is_done(item, c):
    if not c:
        return False
    return bool(c["done"]) if item["kind"] == "check" else c["value"] is not None or bool(c["text"])


def score(plan, checks):
    done = [i for i in plan["items"] if is_done(i, checks.get(i["id"]))]
    core = [i["id"] for i in plan["items"] if i.get("core")]
    ids = {i["id"] for i in done}
    showed = bool(done) and all(c in ids for c in core)
    return {"xp": sum(i.get("xp", 0) for i in done), "done": len(done), "total": len(plan["items"]),
            "core_done": all(c in ids for c in core) if core else bool(done), "showed_up": showed}


def history(con):
    """Every planned day in order with its score; adds the comeback bonus (showing up after a missed day)."""
    days = [date.fromisoformat(r[0]) for r in con.execute("SELECT day FROM plans ORDER BY day")]
    out, prev_showed = [], None
    for d in days:
        plan = plan_of(con, d)
        s = score(plan, checks_of(con, d))
        s["comeback"] = bool(s["showed_up"] and prev_showed is False)
        s["xp"] += COMEBACK_XP if s["comeback"] else 0
        out.append({"day": d.isoformat(), **s})
        prev_showed = s["showed_up"]
        nxt = d + timedelta(days=1)
        if nxt not in days and nxt < today():
            prev_showed = False  # a day with no plan at all counts as missed
    return out


def level(xp):
    n = 1
    while 50 * (n + 1) * n <= xp:
        n += 1
    names = [x.strip() for x in CFG["LEVEL_NAMES"].split(",") if x.strip()]
    name = names[n - 1] if n <= len(names) else f"Level {n}"
    lo, hi = 50 * n * (n - 1), 50 * (n + 1) * n
    return {"level": n, "name": name, "xp": xp, "next_at": hi, "progress": round(100 * (xp - lo) / (hi - lo))}


def xp_summary(con):
    h = history(con)
    total = sum(x["xp"] for x in h)
    t = today()

    def window(a, b):
        return [x for x in h if a <= (t - date.fromisoformat(x["day"])).days < b]
    return {**level(total), "xp_this_week": sum(x["xp"] for x in window(0, 7)),
            "xp_last_week": sum(x["xp"] for x in window(7, 14)),
            "showed_up_7": sum(x["showed_up"] for x in window(0, 7)),
            "showed_up_28": sum(x["showed_up"] for x in window(0, 28)),
            "yesterday_missed": bool(h) and not any(x["day"] == (t - timedelta(days=1)).isoformat()
                                                    and x["showed_up"] for x in h)}


ID = re.compile(r"^[a-z0-9_]{1,32}$")


def clean(s, n):
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(s)).strip()[:n]


def validate(plan, day):
    if not isinstance(plan, dict):
        raise ValueError("plan must be a JSON object")
    unknown = set(plan) - {"date", "readiness", "headline", "why", "items", "recipe", "tip", "weekly", "ack"}
    if unknown:
        raise ValueError(f"unknown keys: {sorted(unknown)}")
    if plan.get("date", day.isoformat()) != day.isoformat():
        raise ValueError(f"date must be {day.isoformat()}")
    if plan.get("readiness") not in READINESS:
        raise ValueError(f"readiness must be one of {sorted(READINESS)}")
    items = plan.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 14:
        raise ValueError("items: 1-14 entries")
    out_items, seen = [], set()
    for it in items:
        if not isinstance(it, dict) or not ID.match(str(it.get("id", ""))) or it["id"] in seen:
            raise ValueError(f"item id missing, invalid or duplicate: {it!r:.80}")
        if it.get("kind") not in KINDS:
            raise ValueError(f"{it['id']}: kind must be one of {sorted(KINDS)}")
        xp = it.get("xp", 0)
        if not isinstance(xp, int) or not 0 <= xp <= 50:
            raise ValueError(f"{it['id']}: xp must be an int 0-50")
        seen.add(it["id"])
        o = {"id": it["id"], "kind": it["kind"], "label": clean(it.get("label", ""), 160), "xp": xp,
             "cat": clean(it.get("cat", ""), 16), "core": bool(it.get("core"))}
        if not o["label"]:
            raise ValueError(f"{it['id']}: label required")
        for k, n in (("hint", 300), ("unit", 12)):
            if it.get(k):
                o[k] = clean(it[k], n)
        if it.get("metric"):
            if not ID.match(str(it["metric"])):
                raise ValueError(f"{it['id']}: metric must match {ID.pattern}")
            o["metric"] = it["metric"]
        out_items.append(o)
    out = {"date": day.isoformat(), "readiness": plan["readiness"], "items": out_items}
    for k, n in (("headline", 120), ("why", 600), ("tip", 400), ("weekly", 900), ("ack", 300)):
        if plan.get(k):
            out[k] = clean(plan[k], n)
    if plan.get("recipe"):
        r = plan["recipe"]
        if not isinstance(r, dict) or not str(r.get("url", "")).startswith("https://") or not r.get("title"):
            raise ValueError("recipe needs title and an https:// url")
        out["recipe"] = {"title": clean(r["title"], 120), "url": clean(r["url"], 500),
                         "why": clean(r.get("why", ""), 300), "time_min": int(r.get("time_min") or 0),
                         "shopping": [clean(x, 60) for x in (r.get("shopping") or [])[:12]]}
    return out


def plan_set(con, path):
    work = os.environ.get("DAILY_COACH_WORK")
    p = Path(path).resolve()
    if work and Path(work).resolve() not in p.parents:
        raise ValueError(f"plan file must be inside {work}")
    day = today()
    plan = validate(json.loads(p.read_text(encoding="utf-8")), day)
    con.execute("INSERT OR REPLACE INTO plans VALUES (?,?,?)", (day.isoformat(), json.dumps(plan, ensure_ascii=False),
                                                              int(time.time())))
    con.commit()
    return plan


def save_check(con, day, item_id, done=None, value=None, text=None):
    plan = plan_of(con, day)
    if not plan or (today() - day).days not in range(0, 8):
        raise ValueError("no plan for that day, or it is more than a week old")
    item = next((i for i in plan["items"] if i["id"] == item_id), None)
    if not item:
        raise ValueError("unknown item")
    if value is not None:
        value = float(value)
        if not math.isfinite(value) or abs(value) > 1e6:
            raise ValueError("bad value")
    con.execute("INSERT OR REPLACE INTO checks VALUES (?,?,?,?,?,?,?)",
                (day.isoformat(), item_id, 1 if done else 0, value, clean(text, 2000) if text else None,
                 item.get("metric"), int(time.time())))
    con.commit()
    return {"today": score(plan, checks_of(con, day)), **xp_summary(con)}


# ---------------------------------------------------------------- context for the morning run

def context(con, days=14):
    t = today()
    nights = [night(con, t - timedelta(days=i)) for i in range(28, -1, -1)]
    last, base = nights[-1], baselines(nights[:-1])
    plans = []
    for i in range(days, 0, -1):
        d = t - timedelta(days=i)
        p = plan_of(con, d)
        if not p:
            plans.append({"day": d.isoformat(), "plan": None})
            continue
        ch = checks_of(con, d)
        plans.append({"day": d.isoformat(), "readiness": p["readiness"], **score(p, ch),
                      "items": [{"id": it["id"], "label": it["label"], "cat": it["cat"], "core": it["core"],
                                 "done": is_done(it, ch.get(it["id"])),
                                 **({"value": ch[it["id"]]["value"]} if ch.get(it["id"], {}).get("value") is not None else {}),
                                 **({"note": ch[it["id"]]["text"]} if ch.get(it["id"], {}).get("text") else {})}
                                for it in p["items"]],
                      "recipe": (p.get("recipe") or {}).get("title")})
    cats = defaultdict(lambda: [0, 0])
    for p in plans[-7:]:
        for it in p.get("items", []):
            cats[it["cat"]][0] += it["done"]
            cats[it["cat"]][1] += 1
    measures = defaultdict(list)
    for r in con.execute("SELECT day, metric, value FROM checks WHERE metric IS NOT NULL AND value IS NOT NULL "
                         "ORDER BY day"):
        measures[r["metric"]].append([r["day"], r["value"]])
    recipes = [json.loads(r[0]).get("recipe", {}).get("title") for r in
               con.execute("SELECT plan FROM plans WHERE day>=? ORDER BY day", ((t - timedelta(days=60)).isoformat(),))]
    last_ingest = con.execute("SELECT max(at) FROM events WHERE kind='ingest'").fetchone()[0]
    return {
        "today": t.isoformat(), "weekday": t.strftime("%A"), "now": datetime.now().strftime("%H:%M"),
        "last_sync": datetime.fromtimestamp(last_ingest).isoformat(timespec="minutes") if last_ingest else None,
        "plan_exists_today": plan_of(con, t) is not None,
        "last_night": last, "baseline_28d": base, "readiness": readiness(last, base),
        "nights_7d": nights[-8:-1],
        "steps_14d": {(t - timedelta(days=i)).isoformat(): steps(con, t - timedelta(days=i)) for i in range(14, 0, -1)},
        "xp": xp_summary(con), "category_completion_7d": {k: f"{a}/{b}" for k, (a, b) in cats.items()},
        "days": plans, "measurements": {k: v[-12:] for k, v in measures.items()},
        "recent_recipes": [r for r in recipes if r],
    }


# ---------------------------------------------------------------- app links, notification, auto start

def link(path=""):
    base = CFG["PUBLIC_URL"].rstrip("/")
    return f"{base}/{token()}/{path}" if base else ""


def push():
    return webapp.Push(DATA, CFG["PUBLIC_URL"] or "mailto:daily-coach@localhost")


def latest(con):
    """What a push notification says: the newest plan's headline and its floor."""
    r = con.execute("SELECT day FROM plans ORDER BY day DESC LIMIT 1").fetchone()
    plan = plan_of(con, date.fromisoformat(r[0])) if r else None
    if not plan:
        return {"day": None, "title": "Daily", "body": "No plan yet.", "url": ""}
    core = [i["label"] for i in plan["items"] if i["core"]]
    rec = plan.get("recipe")
    return {"day": plan["date"], "title": f"{READINESS[plan['readiness']]} {plan.get('headline', 'Your plan is ready')}",
            "body": " · ".join(core[:3]) + (f" · 🍲 {rec['title']}" if rec else ""), "url": ""}


def night_over(con, now=None):
    """Last night's sleep ended 20+ min ago and it's past AUTO_PLAN_HOUR: a sync now can start today's plan."""
    now = now or time.time()
    if datetime.fromtimestamp(now).hour < int(CFG["AUTO_PLAN_HOUR"]):
        return False
    t = today()
    end = con.execute("SELECT max(end) FROM samples WHERE metric='sleep' AND text IN (?,?,?,?) AND end>? AND end<=?",
                      (*ASLEEP, at(t - timedelta(days=1), 18), int(now))).fetchone()[0]
    return bool(end) and now - end >= 20 * 60


# ---------------------------------------------------------------- web

CSS = webapp.css(THEME, "#e9f3ee", "#6cc495", "#20352a") + """
.bar{height:8px;background:var(--line);border-radius:99px;overflow:hidden;margin:6px 0}.bar i{display:block;height:100%;background:var(--acc)}
.item{display:flex;gap:12px;align-items:flex-start;padding:12px 0;border-top:1px solid var(--line)}.item:first-child{border-top:0}
.item input[type=checkbox]{width:28px;height:28px;flex:none;accent-color:var(--acc);margin:0}
.item .t{flex:1}.item .xp{color:var(--mute);font-size:13px;white-space:nowrap}.core .t>b:before{content:"★ ";color:var(--acc)}
.done .t>b{text-decoration:line-through;opacity:.6}.row{display:flex;gap:8px;margin-top:6px;flex-wrap:wrap}
input[type=number],textarea{font:inherit;padding:8px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg)}
input[type=number]{width:110px}textarea{width:100%;min-height:60px}
svg{width:100%;height:auto;display:block}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px}"""

JS = """const D=document.body.dataset.day;
async function post(p,b){const r=await fetch(p,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(b)});
const j=await r.json();if(!r.ok){alert(j.error||'failed');return null}return j}
function upd(j){if(!j)return;document.getElementById('xp').textContent=j.name+' · '+j.xp+' XP';document.getElementById('xpbar').style.width=j.progress+'%';
document.getElementById('xpday').textContent=j.today.xp+' XP today · '+j.today.done+'/'+j.today.total+' done'+(j.today.showed_up?' · showed up ✓':'')}
document.querySelectorAll('[data-id]').forEach(el=>{const id=el.dataset.id,k=el.dataset.kind,box=el.closest('.item');
if(k==='check')el.addEventListener('change',async()=>{box.classList.toggle('done',el.checked);upd(await post('api/check',{day:D,id,done:el.checked}))});
if(k==='number'||k==='text')el.querySelector('button').addEventListener('click',async()=>{const f=el.querySelector('input,textarea');
const v=f.value.trim();const j=await post('api/check',{day:D,id,...(k==='number'?{value:v===''?null:v.replace(',','.')}:{text:v})});if(j){box.classList.toggle('done',v!=='');upd(j)}});
if(k==='scale')el.querySelectorAll('button').forEach(b=>b.addEventListener('click',async()=>{el.querySelectorAll('button').forEach(x=>x.classList.remove('on'));
b.classList.add('on');box.classList.add('done');upd(await post('api/check',{day:D,id,value:+b.textContent}))}))});
const w=document.getElementById('wake');if(w)w.addEventListener('click',async()=>{w.disabled=true;const j=await post('wake',{});if(j)w.textContent=j.status});
const W=document.body.dataset.waiting;if(W)setInterval(()=>fetch('api/latest',{cache:'no-store'}).then(r=>r.json())
.then(j=>{if(j.day===W)location.reload()}).catch(()=>0),30000)"""


@lru_cache(maxsize=1)
def vapid():
    try:
        return push().public_key()
    except (OSError, subprocess.SubprocessError):
        return ""  # no openssl: the app works, just without notifications


def page(title, body, day="", waiting=""):
    return f"""<!doctype html><html lang="en"><head>{webapp.head("Daily", THEME, vapid())}<title>{html.escape(title)}</title>
<style>{CSS}</style></head><body data-day="{day}" data-waiting="{waiting}" data-at="{datetime.now():%a %H:%M}"><main>{body}
<p class=mute id=push></p></main><script>{JS}</script><script>{webapp.CLIENT_JS}</script></body></html>"""


def item_html(it, c):
    e = html.escape
    done = is_done(it, c)
    label = f"<b>{e(it['label'])}</b>" + (f"<div class=mute>{e(it['hint'])}</div>" if it.get("hint") else "")
    cls = "item" + (" core" if it["core"] else "") + (" done" if done else "")
    xp = f"<span class=xp>+{it['xp']}</span>"
    if it["kind"] == "check":
        return (f"<label class='{cls}'><input type=checkbox data-id='{it['id']}' data-kind=check"
                f"{' checked' if done else ''}><span class=t>{label}</span>{xp}</label>")
    if it["kind"] == "number":
        v = "" if not c or c["value"] is None else f"{c['value']:g}"
        ctl = (f"<div class=row data-id='{it['id']}' data-kind=number><input type=number step=any inputmode=decimal "
               f"value='{v}' placeholder='{e(it.get('unit', ''))}'><button>Save</button></div>")
    elif it["kind"] == "scale":
        v = None if not c else c["value"]
        ctl = f"<div class=row data-id='{it['id']}' data-kind=scale>" + "".join(
            f"<button class='s{' on' if v == n else ''}'>{n}</button>" for n in range(1, 6)) + "</div>"
    else:
        ctl = (f"<div class=row data-id='{it['id']}' data-kind=text style='display:block'><textarea>"
               f"{e(c['text'] or '') if c else ''}</textarea><button>Save</button></div>")
    return f"<div class='{cls}'><span class=t>{label}{ctl}</span>{xp}</div>"


def today_page(con, day):
    """The plan for `day`. Today without a plan yet shows the newest earlier plan under a 'being made' note."""
    e, waiting, notice = html.escape, "", ""
    if day == today() and not plan_of(con, day):
        running = (DATA / "last-trigger").exists() and time.time() - (DATA / "last-trigger").stat().st_mtime < 900
        waiting = day.isoformat()
        msg = ("Today’s plan is being made: this page switches to it by itself." if running else
               "No plan for today yet. It starts when your ring data arrives, or at the fallback time.")
        btn = "" if running else "<button id=wake class=big>I’m up: make my plan</button>"
        prev = con.execute("SELECT day FROM plans WHERE day<? ORDER BY day DESC LIMIT 1", (day.isoformat(),)).fetchone()
        if prev:
            day = date.fromisoformat(prev[0])
            msg += f" Until then, here is {day.strftime('%A')}’s."
        notice = f"<div class=card>{msg}{btn}</div>"
    plan, ch, xp = plan_of(con, day), checks_of(con, day), xp_summary(con)
    nav = (f"<nav><a href='?d={day - timedelta(days=1)}'>← {(day - timedelta(days=1)).strftime('%a')}</a>"
           f"<a href='dashboard'>Trends</a>" + (f"<a href='?d={day + timedelta(days=1)}'>{(day + timedelta(days=1)).strftime('%a')} →</a>"
                                                if day < today() else "<span></span>") + "</nav>")
    s = score(plan, ch) if plan else None
    xpday = f"{s['xp']} XP today · {s['done']}/{s['total']} done" + (" · showed up ✓" if s["showed_up"] else "") if s else ""
    head = (f"<div class=card><div id=xp>{e(xp['name'])} · {xp['xp']} XP</div><div class=bar><i id=xpbar style='width:{xp['progress']}%'></i></div>"
            f"<div class=mute id=xpday>{xpday}</div><div class=mute>Showed up {xp['showed_up_7']}/7 days · {xp['showed_up_28']}/28 · "
            f"{xp['xp_this_week']} XP this week (last week {xp['xp_last_week']})</div></div>")
    if not plan:
        return page("Daily", f"{nav}<h1>{day.strftime('%A %d %b')}</h1>{head}{notice or '<div class=card>No plan for this day.</div>'}",
                    day.isoformat(), waiting)
    n = night(con, day)
    sleep = (f"{n['asleep_h']:.1f} h asleep · {n['bed']}–{n['wake']} · {n['wakes']} wake-ups · deep {n['deep_min']} min"
             if n.get("asleep_h") is not None else "No ring data from last night")
    comeback = "<div class='card'>Comeback day: show up for the ★ items and you get +20 bonus XP.</div>" if xp["yesterday_missed"] and day == today() else ""
    items = "".join(item_html(i, ch.get(i["id"])) for i in plan["items"])
    rec = plan.get("recipe")
    rec_html = (f"<h2>Cook today</h2><div class=card><a href='{e(rec['url'])}'><b>{e(rec['title'])}</b></a>"
                f"<div class=mute>{rec['time_min']} min · {e(rec['why'])}</div>"
                + (f"<div class=mute>Shop: {e(', '.join(rec['shopping']))}</div>" if rec["shopping"] else "") + "</div>") if rec else ""
    body = (f"{nav}{notice}<h1>{READINESS[plan['readiness']]} {e(plan.get('headline', ''))}</h1><div class=mute>{day.strftime('%A %d %b')} · {e(sleep)}</div>"
            f"{head}{comeback}<p>{e(plan.get('ack', ''))} {e(plan.get('why', ''))}</p><h2>Today · ★ = the floor</h2><div class=card>{items}</div>{rec_html}"
            + (f"<h2>Tip</h2><div class=card>{e(plan['tip'])}</div>" if plan.get("tip") else "")
            + (f"<h2>Last week</h2><div class=card>{e(plan['weekly'])}</div>" if plan.get("weekly") else ""))
    return page("Daily", body, day.isoformat(), waiting)


def chart(title, points, unit="", bars=False, digits=1):
    vals = [v for _, v in points if v is not None]
    if not vals:
        return f"<div class=card><b>{html.escape(title)}</b><div class=mute>no data yet</div></div>"
    w, h, pad = 320, 90, 4
    lo, hi = min(vals + [0] if bars else vals), max(vals)
    span = (hi - lo) or 1
    step = (w - 2 * pad) / max(len(points) - 1, 1)

    def y(v):
        return h - pad - (v - lo) / span * (h - 2 * pad)
    if bars:
        bw = max(step * 0.7, 1)
        marks = "".join(f"<rect x='{pad + i * step - bw / 2:.1f}' y='{y(v):.1f}' width='{bw:.1f}' height='{h - pad - y(v):.1f}' rx='1'/>"
                        for i, (_, v) in enumerate(points) if v is not None)
        svg = f"<g fill='var(--acc)'>{marks}</g>"
    else:
        segs, cur = [], []
        for i, (_, v) in enumerate(points):
            if v is None:
                segs, cur = segs + [cur] if cur else segs, []
            else:
                cur.append(f"{pad + i * step:.1f},{y(v):.1f}")
        segs += [cur] if cur else []
        svg = "".join(f"<polyline fill='none' stroke='var(--acc)' stroke-width='2' points='{' '.join(s)}'/>" for s in segs)
        svg += "".join(f"<circle cx='{s[-1].split(',')[0]}' cy='{s[-1].split(',')[1]}' r='3' fill='var(--acc)'/>" for s in segs[-1:])
    last = next(((d, v) for d, v in reversed(points) if v is not None))
    avg = statistics.mean(vals)
    return (f"<div class=card><b>{html.escape(title)}</b> <span class=mute>latest {last[1]:.{digits}f}{unit} ({last[0][5:]}) · "
            f"avg {avg:.{digits}f} · range {min(vals):.{digits}f}–{max(vals):.{digits}f}</span>"
            f"<svg viewBox='0 0 {w} {h}' role=img aria-label='{html.escape(title)}'>{svg}</svg></div>")


def dashboard(con, days):
    t = today()
    span = [t - timedelta(days=i) for i in range(days - 1, -1, -1)]
    nights = {d: night(con, d) for d in span}
    hist = {x["day"]: x for x in history(con)}
    series = [("Sleep (h)", "asleep_h", " h", True, 1), ("Wake-ups", "wakes", "", True, 0), ("Deep sleep (min)", "deep_min", "", True, 0),
              ("HRV (ms)", "hrv", " ms", False, 0), ("Resting HR", "rhr", " bpm", False, 0), ("SpO2 avg", "spo2", "%", False, 1),
              ("Temperature", "temp", "°", False, 2)]
    cards = [chart(title, [(d.isoformat(), nights[d].get(k)) for d in span], unit, bars, dg) for title, k, unit, bars, dg in series]
    cards.insert(0, chart("XP per day", [(d.isoformat(), (hist.get(d.isoformat()) or {}).get("xp")) for d in span], "", True, 0))
    cards.insert(1, chart("Steps", [(d.isoformat(), steps(con, d)) for d in span], "", True, 0))
    for metric in sorted({r[0] for r in con.execute("SELECT DISTINCT metric FROM checks WHERE metric IS NOT NULL")}):
        vals = dict(con.execute("SELECT day, value FROM checks WHERE metric=? AND value IS NOT NULL", (metric,)).fetchall())
        cards.append(chart(metric.replace("_", " ").capitalize(), [(d.isoformat(), vals.get(d.isoformat())) for d in span]))
    nav = "<nav><a href='./'>← Today</a>" + "".join(f"<a href='?days={n}'>{n}d</a>" for n in (14, 30, 90, 365)) + "</nav>"
    return page("Trends", f"{nav}<h1>Trends · {days} days</h1><div class=grid>{''.join(cards)}</div>")


def trigger(con, reason):
    if plan_of(con, today()):
        return "Plan already made for today"
    stamp = DATA / "last-trigger"
    if stamp.exists() and time.time() - stamp.stat().st_mtime < 900:
        return "Plan is being made…"
    stamp.touch()
    con.execute("INSERT INTO events VALUES (?,?,?)", (int(time.time()), "trigger", reason))
    con.commit()
    subprocess.Popen(shlex.split(CFG["TRIGGER"]), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return "Making your plan: it shows up in the app in a few minutes"


class Handler(webapp.AppHandler):
    server_version = "daily-coach"
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
                day = date.fromisoformat(q["d"]) if "d" in q else today()
                return self.send(200, today_page(con, min(day, today())))
            if rest == ["dashboard"]:
                return self.send(200, dashboard(con, max(7, min(int(q.get("days", 30)), 730))))
            if rest == ["api", "today"]:
                return self.send(200, json.dumps({"plan": plan_of(con, today()), **xp_summary(con)}), "application/json")
            if rest == ["api", "latest"]:
                return self.send(200, json.dumps(latest(con), ensure_ascii=False), "application/json")
            if rest == ["api", "ping"]:
                return self.send(200, "{}", "application/json")
            if rest == ["manifest.webmanifest"]:
                return self.send(200, webapp.manifest("Daily", BG, THEME), "application/manifest+json")
            if len(rest) == 1 and (f := webapp.static(rest[0], THEME, "#ffffff", "ring")):
                return self.send(200, *f)
            return self.send(404, "not found", "text/plain")
        except ValueError as ex:
            return self.send(400, str(ex), "text/plain")
        finally:
            con.close()

    def do_POST(self):
        rest, q = self.route()
        if rest is None:
            return self.send(404, "not found", "text/plain")
        try:
            body = self.body(8_000_000)
        except ValueError:
            return self.send(413, "too large", "text/plain")
        con = db()
        try:
            if rest == ["ingest"]:
                res = ingest(con, body)
                if q.get("wake") == "1":
                    res["status"] = trigger(con, "wake")
                elif not plan_of(con, today()) and night_over(con):
                    res["status"] = trigger(con, "auto")
                return self.send(200, json.dumps(res, ensure_ascii=False), "application/json")
            if rest == ["api", "push"]:
                return self.send(200, json.dumps({"devices": push().subscribe(json.loads(body or "{}"))}), "application/json")
            if rest == ["wake"]:
                return self.send(200, json.dumps({"status": trigger(con, "button")}), "application/json")
            if rest == ["api", "check"]:
                b = json.loads(body or "{}")
                res = save_check(con, date.fromisoformat(b["day"]), str(b["id"]), b.get("done"),
                                 b.get("value"), b.get("text"))
                return self.send(200, json.dumps(res), "application/json")
            return self.send(404, json.dumps({"error": "not found"}), "application/json")
        except (ValueError, KeyError, TypeError) as ex:
            return self.send(400, json.dumps({"error": str(ex)}), "application/json")
        finally:
            con.close()


def serve():
    db().close()
    webapp.serve("daily-coach", Handler, CFG["BIND"], CFG["PORT"])


def status(con):
    t = today()
    last = con.execute("SELECT at, detail FROM events WHERE kind='ingest' ORDER BY at DESC LIMIT 1").fetchone()
    print(f"last sync: {datetime.fromtimestamp(last[0]):%Y-%m-%d %H:%M} ({last[1]})" if last else "last sync: never")
    since = at(t - timedelta(days=3), 0)
    for r in con.execute("SELECT metric, count(*), group_concat(DISTINCT raw) FROM samples WHERE start>=? GROUP BY metric",
                         (since,)):
        print(f"  {r[0]:<12} {r[1]:>6} samples (last 3 days)" + (f"  UNKNOWN type: {r[2]}" if r[0].startswith("raw:") else ""))
    n = night(con, t)
    print("last night:", json.dumps({k: v for k, v in n.items() if v is not None}, ensure_ascii=False))
    print("plan today:", "yes" if plan_of(con, t) else "no")
    x = xp_summary(con)
    print(f"xp: {x['name']} {x['xp']} XP · showed up {x['showed_up_7']}/7")
    last = con.execute("SELECT at, detail FROM events WHERE kind='notify' ORDER BY at DESC LIMIT 1").fetchone()
    print(f"push: {len(push().subs())} device(s)" + (f", last {datetime.fromtimestamp(last[0]):%m-%d %H:%M} ({last[1]})" if last else ""))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    sub.add_parser("ingest").add_argument("file")
    sub.add_parser("context").add_argument("--days", type=int, default=14)
    sub.add_parser("plan-set").add_argument("file")
    for c in ("notify", "has-plan", "status", "url"):
        sub.add_parser(c)
    a = ap.parse_args()
    if a.cmd == "serve":
        return serve()
    if a.cmd == "url":
        if not CFG["PUBLIC_URL"]:
            sys.exit(f"daily-coach: set PUBLIC_URL in {CONF}")
        return print(f"app:      {link()}\ntrends:   {link('dashboard')}\nsync:     {link('ingest')}\n"
                     f"morning:  {link('ingest?wake=1')}")
    con = db()
    try:
        if a.cmd == "ingest":
            print(json.dumps(ingest(con, Path(a.file).read_text(encoding="utf-8"))))
        elif a.cmd == "context":
            print(json.dumps(context(con, a.days), ensure_ascii=False, separators=(",", ":")))
        elif a.cmd == "plan-set":
            plan = plan_set(con, a.file)
            print(f"plan stored for {plan['date']}: {len(plan['items'])} items")
        elif a.cmd == "notify":
            sent, dropped = push().send()
            con.execute("INSERT INTO events VALUES (?,?,?)", (int(time.time()), "notify", f"sent={sent} dropped={dropped}"))
            con.commit()
            print(f"pushed to {sent} device(s), dropped {dropped} expired")
        elif a.cmd == "has-plan":
            sys.exit(0 if plan_of(con, today()) else 1)
        elif a.cmd == "status":
            status(con)
    except (ValueError, json.JSONDecodeError, OSError) as ex:
        sys.exit(f"daily-coach: {ex}")


if __name__ == "__main__":
    main()
