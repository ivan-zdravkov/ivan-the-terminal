#!/usr/bin/env -S python3 -I
"""daily-coach: health samples, daily plans and check-ins in one SQLite file. Stdlib only.

  coach.py import [--no-fetch]   fetch the private repo and ingest new Health sync files (HEALTH_REPO, HEALTH_DIR)
  coach.py ingest FILE           store samples from a file (the same 'type|start|end|value|unit|source' lines)
  coach.py ready                 exit 0 if last night ended 20+ min ago and it's past AUTO_PLAN_HOUR, 1 if not
  coach.py context [--days N]    JSON for the morning run: nights, vitals vs baseline, readiness, check-ins, XP
  coach.py checks-set FILE       store check-ins from the candidate's replies (FILE inside $DAILY_COACH_WORK when set)
  coach.py plan-set FILE         validate and store today's plan (FILE must be inside $DAILY_COACH_WORK when set)
  coach.py email                 JSON {to, subject, html, text}: today's plan as the morning email
  coach.py has-plan              exit 0 if today has a plan, 1 if not
  coach.py status                last import, metrics seen, unknown sample types, today's plan, XP

Config: ~/.config/ivan-the-terminal/daily-coach/config.env (see ../config.example). Data: ~/.local/share/ivan-the-terminal/daily-coach/
"""
import argparse
import html
import importlib.util
import json
import math
import os
import re
import sqlite3
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

HOME = Path.home()
CONF = Path(os.environ.get("DAILY_COACH_CONF") or
            Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "ivan-the-terminal/daily-coach/config.env")
DATA = Path(os.environ.get("DAILY_COACH_DATA") or
            Path(os.environ.get("XDG_DATA_HOME", HOME / ".local/share")) / "ivan-the-terminal/daily-coach")
DEFAULTS = {"MAIL_TO": "", "DAY_START_HOUR": "4", "AUTO_PLAN_HOUR": "6", "LEVEL_NAMES": "", "WEB_DOMAINS": "",
            "HEALTH_REPO": "", "HEALTH_DIR": "health", "HEALTH_REF": "origin/main"}
_spec = importlib.util.spec_from_file_location("envfile", Path(__file__).resolve().parents[5] / "tools/envfile.py")
envfile = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(envfile)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # Windows task: no console flashing for git

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
SUBJECT = "Daily plan"  # every plan email's subject starts with this: the run finds replies by it


# ---------------------------------------------------------------- config, db, time

def config():
    return envfile.env(CONF, DEFAULTS)


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
      CREATE TABLE IF NOT EXISTS imported(name TEXT PRIMARY KEY, at INTEGER);
    """)
    return con


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


LINKISH = re.compile(r"(?i)://|www\.|\b[a-z0-9-]{2,}\.[a-z]{2,}\b")


def text(s, n):
    """Plan text goes into an email, where mail clients turn URLs and bare domains into links. The only link a plan
    may carry is the recipe's, on a WEB_DOMAINS site: anything else could carry data out of the run."""
    s = clean(s, n)
    if LINKISH.search(s):
        raise ValueError(f"no links or domain names in plan text (only recipe.url): {s[:60]!r}")
    return s


# Strict on purpose: no userinfo, backslash or whitespace, so Python and browsers can't disagree about the host
# (urlparse reads "https://evil.example\@good.example/" as good.example; a browser goes to evil.example).
SAFE_URL = re.compile(r"https://([a-z0-9-]+(?:\.[a-z0-9-]+)+)(?::\d{1,5})?(?:[/?#][^\s\\@<>\"'`]*)?", re.I)


def recipe_url(url):
    m = SAFE_URL.fullmatch(str(url))
    host, domains = (m.group(1).lower() if m else ""), CFG["WEB_DOMAINS"].lower().split()
    if not host or not any(host == d or host.endswith("." + d) for d in domains):
        raise ValueError(f"recipe.url must be a plain https:// URL on a WEB_DOMAINS site: {sorted(domains)}")
    return clean(url, 500)


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
        o = {"id": it["id"], "kind": it["kind"], "label": text(it.get("label", ""), 160), "xp": xp,
             "cat": text(it.get("cat", ""), 16), "core": bool(it.get("core"))}
        if not o["label"]:
            raise ValueError(f"{it['id']}: label required")
        for k, n in (("hint", 300), ("unit", 12)):
            if it.get(k):
                o[k] = text(it[k], n)
        if it.get("metric"):
            if not ID.match(str(it["metric"])):
                raise ValueError(f"{it['id']}: metric must match {ID.pattern}")
            o["metric"] = it["metric"]
        out_items.append(o)
    out = {"date": day.isoformat(), "readiness": plan["readiness"], "items": out_items}
    for k, n in (("headline", 120), ("why", 600), ("tip", 400), ("weekly", 900), ("ack", 300)):
        if plan.get(k):
            out[k] = text(plan[k], n)
    if plan.get("recipe"):
        r = plan["recipe"]
        if not isinstance(r, dict) or not r.get("title"):
            raise ValueError("recipe needs a title and an https:// url")
        out["recipe"] = {"title": text(r["title"], 120), "url": recipe_url(r.get("url")),
                         "why": text(r.get("why", ""), 300), "time_min": int(r.get("time_min") or 0),
                         "shopping": [text(x, 60) for x in (r.get("shopping") or [])[:12]]}
    return out


def plan_set(con, path):
    day = today()
    plan = validate(json.loads(work_file(path).read_text(encoding="utf-8")), day)
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


# ---------------------------------------------------------------- Health sync files from the private repo

def git(repo, *args, timeout=60, env=None):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, creationflags=NO_WINDOW,
                          env={**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})})


def fetch(repo):
    """Unattended: never wait on a passphrase prompt. Same ssh as git's own (Windows: OpenSSH and its agent)."""
    ssh = git(repo, "config", "core.sshCommand").stdout.strip() or "ssh"
    try:
        return git(repo, "fetch", "-q", "origin",
                   env={"GIT_SSH_COMMAND": f"{ssh} -o BatchMode=yes -o ConnectTimeout=10"}).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def health_repo():
    """HEALTH_REPO: absolute, ~/..., or relative to the config file's real folder (so a config kept inside that very
    repo can say "../../.." and work wherever the repo is cloned)."""
    if not CFG["HEALTH_REPO"]:
        raise ValueError(f"set HEALTH_REPO (a clone of the repo the phone commits to) in {CONF}")
    p = Path(CFG["HEALTH_REPO"]).expanduser()
    return p if p.is_absolute() else (CONF.resolve().parent / p).resolve()


def import_repo(con, do_fetch=True):
    """The phone commits each Health sync as a file under HEALTH_DIR. Read new ones straight from HEALTH_REF, so the
    clone's working tree (and whatever else is going on in it) is never touched. Already-imported names are skipped."""
    repo, ref, folder = health_repo(), CFG["HEALTH_REF"], CFG["HEALTH_DIR"].strip("/")
    fetched = fetch(repo) if do_fetch else None
    ls = git(repo, "ls-tree", "-r", "--name-only", ref, "--", folder + "/")
    if ls.returncode:
        raise ValueError(f"git ls-tree {ref} in {repo}: {ls.stderr.strip()}")
    done = {r[0] for r in con.execute("SELECT name FROM imported")}
    new = sorted(n for n in ls.stdout.splitlines() if n.endswith((".txt", ".json")) and n not in done)
    res = {"fetched": fetched, "files": 0, "added": 0, "bad": 0}
    for name in new:
        show = git(repo, "show", f"{ref}:{name}")
        if show.returncode:
            continue
        r = ingest(con, show.stdout)
        con.execute("INSERT OR IGNORE INTO imported VALUES (?,?)", (name, int(time.time())))
        con.commit()
        res["files"] += 1
        res["added"] += r["added"]
        res["bad"] += r["bad"]
    con.execute("INSERT INTO events VALUES (?,?,?)", (int(time.time()), "import", json.dumps(res)))
    con.commit()
    return res


def night_over(con, now=None):
    """Last night's sleep ended 20+ min ago and it's past AUTO_PLAN_HOUR: today's plan can be made."""
    now = now or time.time()
    if datetime.fromtimestamp(now).hour < int(CFG["AUTO_PLAN_HOUR"]):
        return False
    t = today()
    end = con.execute("SELECT max(end) FROM samples WHERE metric='sleep' AND text IN (?,?,?,?) AND end>? AND end<=?",
                      (*ASLEEP, at(t - timedelta(days=1), 18), int(now))).fetchone()[0]
    return bool(end) and now - end >= 20 * 60


# ---------------------------------------------------------------- check-ins from email replies

def work_file(path):
    work = os.environ.get("DAILY_COACH_WORK")
    p = Path(path).resolve()
    if work and Path(work).resolve() not in p.parents:
        raise ValueError(f"file must be inside {work}")
    return p


def checks_set(con, path):
    """[{"day": "YYYY-MM-DD", "id": "<item id>", "done": true | "value": 91.8 | "text": "..."}]: what the candidate
    reported in replies to the plan emails. Each entry replaces that item's check-in."""
    data = json.loads(work_file(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("checks")
    if not isinstance(data, list) or len(data) > 100:
        raise ValueError("expected a list of at most 100 check-ins")
    stored, errors = 0, []
    for c in data:
        try:
            save_check(con, date.fromisoformat(str(c["day"])), str(c["id"]), c.get("done"), c.get("value"),
                       c.get("text"))
            stored += 1
        except (ValueError, KeyError, TypeError) as ex:
            errors.append(f"{c!r:.80}: {ex}")
    return {"stored": stored, "errors": errors, **xp_summary(con)}


# ---------------------------------------------------------------- the morning email

def email(con, day=None):
    day = day or today()
    plan = plan_of(con, day)
    if not plan:
        raise ValueError(f"no plan for {day}")
    e, ch, xp, n = html.escape, checks_of(con, day), xp_summary(con), night(con, day)
    sleep = (f"{n['asleep_h']:.1f} h asleep · {n['bed']}–{n['wake']} · {n['wakes']} wake-ups · deep {n['deep_min']} min"
             if n.get("asleep_h") is not None else "No ring data from last night")
    level = (f"{xp['name']} · {xp['xp']} XP ({xp['progress']}% to the next level) · showed up {xp['showed_up_7']}/7 days"
             f" · {xp['xp_this_week']} XP this week (last week {xp['xp_last_week']})")
    comeback = "Comeback day: do the ★ items and you get +20 bonus XP." if xp["yesterday_missed"] else ""
    head = f"{READINESS[plan['readiness']]} {plan.get('headline', 'Your plan')}"
    subject = " ".join(f"{SUBJECT} {day.isoformat()}: {head}".split())  # one header line

    def entry(it):
        star = "★ " if it["core"] else ""
        ask = {"number": f": ___ {it.get('unit', '')}".rstrip(), "scale": " (1-5)", "text": ": …"}.get(it["kind"], "")
        mark = "☑" if is_done(it, ch.get(it["id"])) else "☐"
        return mark, star, it["label"] + ask, it.get("hint", ""), it["xp"], it["id"]
    items = [entry(it) for it in plan["items"]]
    rec, tip, weekly = plan.get("recipe"), plan.get("tip"), plan.get("weekly")
    reply = ("Reply to this email with what you did, in any words, e.g. \"done swings and the walk, weight 91.8, "
             "energy 4, note: kids were sick\". Tomorrow's plan counts it.")

    mute = "color:#667;font-size:13px"
    rows = "".join(f"<li style='margin:8px 0;list-style:none'>{m} {e(s)}<b>{e(lbl)}</b> <span style='{mute}'>+{x} XP"
                   f" · {e(i)}</span>" + (f"<br><span style='{mute}'>{e(h)}</span>" if h else "") + "</li>"
                   for m, s, lbl, h, x, i in items)
    parts = [f"<h2 style='margin:0 0 4px'>{e(head)}</h2>",
             f"<div style='{mute}'>{day.strftime('%A %d %b')} · {e(sleep)}</div>",
             f"<p style='{mute}'>{e(level)}</p>"]
    if comeback:
        parts.append(f"<p><b>{e(comeback)}</b></p>")
    if plan.get("ack") or plan.get("why"):
        parts.append(f"<p>{e(plan.get('ack', ''))} {e(plan.get('why', ''))}</p>")
    parts.append(f"<h3>Today · ★ = the floor</h3><ul style='padding:0'>{rows}</ul>")
    if rec:
        shop = f"<br><span style='{mute}'>Shop: {e(', '.join(rec['shopping']))}</span>" if rec["shopping"] else ""
        parts.append(f"<h3>Cook today</h3><p><a href='{e(rec['url'])}'><b>{e(rec['title'])}</b></a>"
                     f"<br><span style='{mute}'>{rec['time_min']} min · {e(rec['why'])}</span>{shop}</p>")
    if tip:
        parts.append(f"<h3>Tip</h3><p>{e(tip)}</p>")
    if weekly:
        parts.append(f"<h3>Last week</h3><p>{e(weekly)}</p>")
    parts.append(f"<p style='{mute}'>{e(reply)}</p>")
    body = "<div style='font-family:sans-serif;max-width:640px'>" + "".join(parts) + "</div>"

    text = [head, f"{day.strftime('%A %d %b')} · {sleep}", level, comeback,
            f"{plan.get('ack', '')} {plan.get('why', '')}".strip(), "", "Today · ★ = the floor"]
    text += [f"{m} {s}{lbl}  (+{x} XP · {i})" + (f"\n    {h}" if h else "") for m, s, lbl, h, x, i in items]
    if rec:
        text += ["", f"Cook today: {rec['title']} ({rec['time_min']} min)", rec["url"], rec["why"]]
        text += [f"Shop: {', '.join(rec['shopping'])}"] if rec["shopping"] else []
    text += ["", f"Tip: {tip}" if tip else "", f"Last week: {weekly}" if weekly else "", "", reply]
    return {"to": CFG["MAIL_TO"], "subject": subject, "html": body, "text": "\n".join(text)}


# ---------------------------------------------------------------- status, CLI

def status(con):
    t = today()
    last = con.execute("SELECT at, detail FROM events WHERE kind='import' ORDER BY at DESC LIMIT 1").fetchone()
    print(f"last import: {datetime.fromtimestamp(last[0]):%Y-%m-%d %H:%M} {last[1]}" if last else "last import: never")
    files = con.execute("SELECT count(*), max(name) FROM imported").fetchone()
    print(f"sync files: {files[0]} imported" + (f", newest {files[1]}" if files[1] else ""))
    since = at(t - timedelta(days=3), 0)
    for r in con.execute("SELECT metric, count(*), group_concat(DISTINCT raw) FROM samples WHERE start>=? GROUP BY metric",
                         (since,)):
        print(f"  {r[0]:<12} {r[1]:>6} samples (last 3 days)" + (f"  UNKNOWN type: {r[2]}" if r[0].startswith("raw:") else ""))
    n = night(con, t)
    print("last night:", json.dumps({k: v for k, v in n.items() if v is not None}, ensure_ascii=False))
    print("ready:", "yes" if night_over(con) else "no", "· plan today:", "yes" if plan_of(con, t) else "no")
    x = xp_summary(con)
    print(f"xp: {x['name']} {x['xp']} XP · showed up {x['showed_up_7']}/7")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("import").add_argument("--no-fetch", action="store_true")
    sub.add_parser("ingest").add_argument("file")
    sub.add_parser("context").add_argument("--days", type=int, default=14)
    sub.add_parser("plan-set").add_argument("file")
    sub.add_parser("checks-set").add_argument("file")
    for c in ("ready", "email", "has-plan", "status"):
        sub.add_parser(c)
    a = ap.parse_args()
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8")
    con = db()
    try:
        if a.cmd == "import":
            print(json.dumps(import_repo(con, do_fetch=not a.no_fetch)))
        elif a.cmd == "ingest":
            print(json.dumps(ingest(con, Path(a.file).read_text(encoding="utf-8"))))
        elif a.cmd == "ready":
            sys.exit(0 if night_over(con) else 1)
        elif a.cmd == "context":
            print(json.dumps(context(con, a.days), ensure_ascii=False, separators=(",", ":")))
        elif a.cmd == "plan-set":
            plan = plan_set(con, a.file)
            print(f"plan stored for {plan['date']}: {len(plan['items'])} items")
        elif a.cmd == "checks-set":
            print(json.dumps(checks_set(con, a.file), ensure_ascii=False))
        elif a.cmd == "email":
            print(json.dumps(email(con), ensure_ascii=False))
        elif a.cmd == "has-plan":
            sys.exit(0 if plan_of(con, today()) else 1)
        elif a.cmd == "status":
            status(con)
    except (ValueError, json.JSONDecodeError, OSError) as ex:
        sys.exit(f"daily-coach: {ex}")


if __name__ == "__main__":
    main()
