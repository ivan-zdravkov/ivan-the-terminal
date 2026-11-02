#!/usr/bin/env python3
"""Add a PC game (exe/bat/cmd) to Steam as a non-Steam game and to Apollo/Sunshine, both with art.

  addgame.py add <launcher> [--name N] [--args A] [--sgdb-id ID] [--admin|--no-admin] [--no-steam] [--no-apollo]
                 [--dry-run]
  addgame.py add --batch games.json   many games at once: one Steam restart, one Apollo write (one UAC prompt)
  addgame.py list                     games in Steam shortcuts and the Apollo app list
  addgame.py remove <name> [--no-steam] [--no-apollo] [--dry-run]

Art: SteamGridDB when STEAMGRIDDB_API_KEY is in the environment or decryptable from SGDB_SECRET, else the official Steam store art
for the matching store title, plus an IGDB cover (via LizardByte GameDB, Apollo's own cover finder) for Apollo.
Config: ~/.config/ivan-the-terminal/add-game.conf (template: config.example). Problems-only output + one summary line.
"""
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.parse
import urllib.request
import uuid
import zlib
from pathlib import Path

WINDOWS = os.name == "nt"
CONF = Path.home() / ".config" / "ivan-the-terminal" / "add-game.conf"
UA = {"User-Agent": "ivan-the-terminal-add-game/0.1"}
SGDB = "https://www.steamgriddb.com/api/v2"
GAMEDB = "https://raw.githubusercontent.com/LizardByte/GameDB/gh-pages"
LAUNCHERS = {".exe", ".bat", ".cmd"}


def die(msg):
    sys.exit(f"add-game: {msg}")


def load_conf(path=CONF):
    defaults = {
        "STEAM_DIR": r"C:\Program Files (x86)\Steam" if WINDOWS else str(Path.home() / ".local/share/Steam"),
        "APOLLO_CONFIG": r"C:\Program Files\Apollo\config",
        "APOLLO_SERVICE": "ApolloService",
        "APOLLO_VIRTUAL_DISPLAY": "1",
        "SGDB_SECRET": "",
    }
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r'\s*([A-Z_]+)=("?)(.*?)\2\s*(#.*)?$', line)
            if m:
                defaults[m.group(1)] = m.group(3)
    return defaults


def dotenv_value(text, key):
    for line in text.splitlines():
        k, sep, v = line.partition("=")
        if sep and k.strip() == key:
            return v.strip().strip('"').strip("'")
    return ""


def sgdb_key(conf):
    """STEAMGRIDDB_API_KEY from the environment, else decrypted in memory from SGDB_SECRET with `sops -d`.
    (`sops exec-env` mangles quoted paths with spaces on Windows, so the script asks sops itself.)"""
    key = os.environ.get("STEAMGRIDDB_API_KEY", "")
    secret = Path(os.path.expanduser(conf.get("SGDB_SECRET", ""))) if conf.get("SGDB_SECRET") else None
    if key or not secret:
        return key, None
    if not secret.is_file() or not shutil.which("sops"):
        return "", f"SGDB_SECRET {secret} unreadable or sops missing"
    out = subprocess.run(["sops", "-d", str(secret)], capture_output=True, text=True, encoding="utf-8")
    if out.returncode:
        return "", "sops couldn't decrypt SGDB_SECRET (age key missing?)"
    return dotenv_value(out.stdout, "STEAMGRIDDB_API_KEY"), None


# ---------- launcher analysis ----------
def analyse(launcher, args=""):
    """What Apollo/Steam need to know about a launcher: command line, admin, services it creates, drivers."""
    p = Path(launcher)
    info = {"path": str(p), "dir": str(p.parent), "kind": p.suffix.lower(), "admin": False,
            "services": [], "drivers": [], "args": args}
    tail = f" {args}" if args else ""
    if info["kind"] == ".exe":
        info["apollo_cmd"] = f'"{p}"{tail}'
        return info
    info["apollo_cmd"] = f'cmd /c ""{p}"{tail}"'
    text = p.read_text(encoding="utf-8", errors="replace")
    info["admin"] = bool(re.search(r"-Verb\s+RunAs|net\s+session|runas\s", text, re.I))
    variables = {k.lower(): v.strip() for k, v in re.findall(r"^\s*set\s+\"?(\w+)=([^\"\r\n]*)\"?", text, re.I | re.M)}

    def expand(s):
        return re.sub(r"%(\w+)%", lambda m: variables.get(m.group(1).lower(), m.group(0)), s).strip('"')

    for m in re.finditer(r"\bsc(?:\.exe)?\s+create\s+(\"[^\"]+\"|\S+)(.*)", text, re.I):
        name, rest = expand(m.group(1)), m.group(2)
        info["services"].append(name)
        if re.search(r"type=\s*kernel", rest, re.I):
            binpath = re.search(r'binPath=\s*"?([^"\r\n]+)"?', rest, re.I)
            if binpath:
                f = expand(binpath.group(1)).replace("%CD%", str(p.parent)).replace("%~dp0", str(p.parent) + "\\")
                info["drivers"].append(str(Path(f)))
    target = re.search(r"\bstart\s+(?:/\w+\s+)*(?:\"\"\s+)?\"?([^\"\r\n]+?\.exe)", expand_all(text, expand), re.I)
    if target:
        info["target"] = str((p.parent / target.group(1).strip().lstrip(".\\/")).resolve())
    return info


def expand_all(text, expand):
    return "\n".join(expand(line) if "%" in line else line for line in text.splitlines())


def signature(path):
    """Authenticode status and signer (Windows); None elsewhere."""
    if not WINDOWS or not Path(path).exists():
        return None
    ps = (f"$s=Get-AuthenticodeSignature -LiteralPath '{path}'; "
          "\"$($s.Status)|$($s.SignerCertificate.Subject -replace ',.*','')\"")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                         encoding="utf-8").stdout.strip()
    return out or None


# ---------- art ----------
def http_json(url, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    return json.load(urllib.request.urlopen(req, timeout=30))


def download(url, dest):
    req = urllib.request.Request(url, headers=UA)
    data = urllib.request.urlopen(req, timeout=60).read()
    Path(dest).write_bytes(data)
    return Path(dest)


def words(s):
    """Significant words: lowercase alphanumerics longer than 2 chars, or digits (sequel numbers matter).
    Accents fold first, so 'Pokémon' matches 'Pokemon'."""
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return [w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2 or w.isdigit()]


def match_score(query, title):
    want, have = words(query), set(words(title))
    if not want:
        return 0.0
    extra = len(have - set(want)) * 0.01  # prefer the plain title over DLC / editions
    return sum(w in have for w in want) / len(want) - extra


def best_match(name, search):
    """Best (id, title) from search(term) for the full name, then for its significant words only (folder names
    abbreviate: 'AC Black Flag' finds Black Flag, not AC/DC). None below a confident score."""
    best = None
    for term in dict.fromkeys([name, " ".join(words(name))]):
        for hid, title in search(term):
            s = match_score(name, title)
            if best is None or s > best[0]:
                best = (s, hid, title)
        if best and best[0] >= 0.99:
            break
    return (best[1], best[2]) if best and best[0] >= 0.74 else None


def sgdb_art(name, key, sgdb_id=None):
    """{'game': (id, name), 'portrait': url, 'portrait_png': url, 'banner': url, 'hero': url, 'logo': url, 'icon': url}"""
    auth = {"Authorization": f"Bearer {key}"}
    if sgdb_id is None:
        hit = best_match(name, lambda t: [(h["id"], h["name"]) for h in http_json(
            f"{SGDB}/search/autocomplete/{urllib.parse.quote(t)}", auth).get("data", [])])
        if not hit:
            return None
        sgdb_id, found = hit
    else:
        found = http_json(f"{SGDB}/games/id/{sgdb_id}", auth)["data"]["name"]
    art = {"game": (sgdb_id, found)}

    def first(kind, **params):
        q = urllib.parse.urlencode({"nsfw": "false", "humor": "false", **params})
        items = http_json(f"{SGDB}/{kind}/game/{sgdb_id}?{q}", auth).get("data", [])
        return items[0]["url"] if items else None

    art["portrait"] = first("grids", dimensions="600x900")
    art["portrait_png"] = first("grids", dimensions="600x900", mimes="image/png")
    art["banner"] = first("grids", dimensions="920x430,460x215")
    art["hero"] = first("heroes")
    art["logo"] = first("logos", mimes="image/png")
    art["icon"] = first("icons", mimes="image/png,image/vnd.microsoft.icon")
    return art


def store_art(name):
    """Official Steam library art for the best store match: portrait, banner, hero (no logos: not in the API)."""
    def search(term):
        q = urllib.parse.urlencode({"term": term, "cc": "us", "l": "en"})
        return [(i["id"], i["name"]) for i in http_json(f"https://store.steampowered.com/api/storesearch/?{q}")
                .get("items", [])]

    hit = best_match(name, search)
    if not hit:
        return None
    appid = hit[0]
    inp = json.dumps({"ids": [{"appid": appid}], "context": {"language": "english", "country_code": "US"},
                      "data_request": {"include_assets": True}})
    item = http_json("https://api.steampowered.com/IStoreBrowseService/GetItems/v1/?"
                     + urllib.parse.urlencode({"input_json": inp}))["response"]["store_items"][0]
    a = item.get("assets", {})
    base = "https://shared.akamai.steamstatic.com/store_item_assets/" + a.get("asset_url_format", "")

    def url(*keys):
        k = next((k for k in keys if k in a), None)
        return base.replace("${FILENAME}", a[k]) if k else None

    return {"game": (appid, item.get("name", hit[1])), "portrait": url("library_capsule_2x", "library_capsule"),
            "banner": url("header_2x", "header"), "hero": url("library_hero_2x", "library_hero")}


def gamedb_cover(name):
    """IGDB cover as PNG, the source Apollo's own cover finder uses: (igdb id, name, url) or None."""
    def search(term):  # GameDB buckets by the first two alphanumerics of the title
        bucket = re.sub(r"[^a-z0-9]", "", term.lower())[:2] or "@"
        try:
            return [(k, v["name"]) for k, v in http_json(f"{GAMEDB}/buckets/{bucket}.json").items()]
        except Exception:
            return []

    hit = best_match(name, search)
    if not hit:
        return None
    g = http_json(f"{GAMEDB}/games/{hit[0]}.json")
    if not g.get("cover", {}).get("url"):
        return None
    img = g["cover"]["url"].rsplit("/", 1)[1].rsplit(".", 1)[0]
    return hit[0], g["name"], f"https://images.igdb.com/igdb/image/upload/t_cover_big_2x/{img}.png"


# ---------- Steam shortcuts.vdf (binary VDF) ----------
def vdf_parse(buf, i=0):
    out = {}
    while True:
        t = buf[i]
        i += 1
        if t == 0x08:
            return out, i
        end = buf.index(b"\0", i)
        key = buf[i:end].decode("utf-8")
        i = end + 1
        if t == 0x00:
            out[key], i = vdf_parse(buf, i)
        elif t == 0x01:
            end = buf.index(b"\0", i)
            out[key] = buf[i:end].decode("utf-8")
            i = end + 1
        elif t == 0x02:
            out[key] = struct.unpack_from("<i", buf, i)[0]
            i += 4
        else:
            raise ValueError(f"unknown VDF type {t:#x} at {i}")


def vdf_dump(d):
    b = b""
    for k, v in d.items():
        kb = k.encode("utf-8") + b"\0"
        if isinstance(v, dict):
            b += b"\x00" + kb + vdf_dump(v)
        elif isinstance(v, int):
            b += b"\x02" + kb + struct.pack("<i", v)
        else:
            b += b"\x01" + kb + v.encode("utf-8") + b"\0"
    return b + b"\x08"


def read_shortcuts(vdf):
    if not vdf.is_file() or not vdf.stat().st_size:
        return {}
    return vdf_parse(vdf.read_bytes())[0].get("shortcuts", {})


def write_shortcuts(vdf, sc):
    entries = {str(i): v for i, v in enumerate(sc.values())}  # Steam expects 0..n-1
    vdf.write_bytes(b"\x00shortcuts\x00" + vdf_dump(entries) + b"\x08")


def shortcut_id(exe_quoted, name):
    return (zlib.crc32((exe_quoted + name).encode("utf-8")) & 0xFFFFFFFF) | 0x80000000


def signed(u):
    return struct.unpack("<i", struct.pack("<I", u))[0]


def steam_users(steam_dir):
    root = Path(steam_dir) / "userdata"
    return sorted(u for u in root.glob("*") if u.is_dir() and u.name.isdigit() and u.name != "0") if root.is_dir() else []


def steam_running():
    if WINDOWS:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq steam.exe", "/NH"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout
        return "steam.exe" in out.lower()
    return subprocess.run(["pgrep", "-x", "steam"], capture_output=True).returncode == 0


def steam_exe(steam_dir):
    return str(Path(steam_dir) / "steam.exe") if WINDOWS else (shutil.which("steam") or "steam")


def stop_steam(steam_dir):
    subprocess.run([steam_exe(steam_dir), "-shutdown"], capture_output=True)
    for _ in range(60):
        if not steam_running():
            return True
        time.sleep(1)
    return False


def start_steam(steam_dir):
    flags = {"creationflags": 0x00000008} if WINDOWS else {"start_new_session": True}  # DETACHED_PROCESS
    subprocess.Popen([steam_exe(steam_dir)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **flags)


def steam_entry(name, launcher, icon="", args=""):
    p = Path(launcher)
    exe = f'"{p}"'
    return shortcut_id(exe, name), {
        "appid": signed(shortcut_id(exe, name)), "AppName": name, "Exe": exe, "StartDir": f'"{p.parent}\\"',
        "icon": icon or str(p), "ShortcutPath": "", "LaunchOptions": args, "IsHidden": 0, "AllowDesktopConfig": 1,
        "AllowOverlay": 1, "OpenVR": 0, "Devkit": 0, "DevkitGameID": "", "DevkitOverrideAppID": 0,
        "LastPlayTime": 0, "FlatpakAppID": "", "tags": {},
    }


def upsert_shortcut(sc, name, entry):
    """Replace the entry with the same AppName (keeping play time and tags) or append. Returns the stored entry."""
    for k, v in sc.items():
        if v.get("AppName") == name:
            entry = {**entry, "appid": v.get("appid", entry["appid"]), "LastPlayTime": v.get("LastPlayTime", 0),
                     "tags": v.get("tags", {})}
            sc[k] = entry
            return entry
    sc[str(len(sc))] = entry
    return entry


# ---------- Apollo ----------
def apollo_entry(name, info, cover, virtual_display, existing=None):
    e = dict(existing or {})
    e.update({"name": name, "cmd": info["apollo_cmd"], "working-dir": info["dir"]})
    e["uuid"] = e.get("uuid") or str(uuid.uuid4()).upper()
    if cover:
        e["image-path"] = str(cover)
    if virtual_display:
        e["virtual-display"] = True
    if info["admin"]:
        e["elevated"] = True
    if info["services"]:
        undo = " & ".join(f"sc stop {s} & sc delete {s}" for s in info["services"])
        e["prep-cmd"] = [{"do": "", "undo": f'cmd /c "{undo}"', "elevated": True}]
    return e


def upsert_app(apps, entry):
    for i, a in enumerate(apps["apps"]):
        if a.get("name") == entry["name"]:
            apps["apps"][i] = entry
            return "updated"
    apps["apps"].append(entry)
    return "added"


def apply_apollo(conf, apps, files, dry):
    """Write apps.json + covers into the Apollo config dir and restart Apollo. Elevated on Windows (one UAC prompt)."""
    cfg = Path(conf["APOLLO_CONFIG"])
    stage = Path(tempfile.mkdtemp(prefix="add-game-"))
    (stage / "apps.json").write_text(json.dumps(apps, indent=4, ensure_ascii=False), encoding="utf-8")
    copies = [(stage / "apps.json", cfg / "apps.json")] + [(Path(s), cfg / "covers" / Path(s).name) for s in files]
    if dry:
        print(f"dry-run: would write {cfg / 'apps.json'} and restart {conf['APOLLO_SERVICE']}")
        return True
    if not WINDOWS:
        (cfg / "covers").mkdir(parents=True, exist_ok=True)
        for src, dst in copies:
            shutil.copy(src, dst)
        print(f"wrote {cfg / 'apps.json'}; restart Sunshine/Apollo to load it")
        return True
    lines = [f"New-Item -ItemType Directory -Force -LiteralPath '{cfg / 'covers'}' | Out-Null",
             f"Copy-Item -LiteralPath '{cfg / 'apps.json'}' -Destination '{cfg / 'apps.json.bak'}' -Force"]
    lines += [f"Copy-Item -LiteralPath '{s}' -Destination '{d}' -Force" for s, d in copies]
    lines += [f"Restart-Service {conf['APOLLO_SERVICE']}", f"'ok' | Set-Content -LiteralPath '{stage / 'done'}'"]
    (stage / "apply.ps1").write_text("\n".join(lines) + "\n", encoding="utf-8")
    runner = shutil.which("pwsh") or "powershell"
    subprocess.run([runner, "-NoProfile", "-Command",
                    f"Start-Process '{runner}' -Verb RunAs -Wait -ArgumentList "
                    f"'-NoProfile','-ExecutionPolicy','Bypass','-File','\"{stage / 'apply.ps1'}\"'"],
                   capture_output=True)
    if not (stage / "done").exists():
        print("PROBLEM apollo: the elevated step didn't finish (UAC declined?); apps.json unchanged")
        return False
    return True


def read_apps(conf):
    f = Path(conf["APOLLO_CONFIG"]) / "apps.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {"apps": [], "env": {}, "version": 2}


# ---------- commands ----------
def prepare(job, key):
    """Resolve one game: launcher analysis, driver checks, art downloads. Returns a dict; 'skip' = don't write."""
    launcher = Path(job["launcher"]).resolve()
    g = {"launcher": launcher, "problems": [], "notes": [], "files": {}, "cover": None, "cover_src": None}
    if not launcher.is_file():
        return {**g, "name": job.get("name") or str(launcher), "skip": f"no such file: {launcher}"}
    if launcher.suffix.lower() not in LAUNCHERS:
        return {**g, "name": job.get("name") or str(launcher), "skip": f"launcher must be one of {sorted(LAUNCHERS)}"}
    if job.get("args") and not job.get("name"):
        return {**g, "name": str(launcher), "skip": "--args needs --name (the folder name is the emulator's)"}
    g["name"] = name = job.get("name") or launcher.parent.name
    g["info"] = info = analyse(launcher, job.get("args", ""))
    if job.get("admin") is not None:
        info["admin"] = job["admin"]
    for d in info["drivers"]:
        sig = signature(d)
        g["notes"].append(f"kernel driver {d}: {sig or 'signature unknown'}")
        if sig and not sig.startswith("Valid"):
            g["skip"] = f"kernel driver {d} is not validly signed ({sig}); not added - check it first"
    if info.get("target"):
        g["notes"].append(f"launches {Path(info['target']).name}: {signature(info['target']) or 'signature unknown'}")
    if g.get("skip"):
        return g

    work = Path(tempfile.mkdtemp(prefix="add-game-art-"))
    art, source = None, None
    try:
        if key:
            art, source = sgdb_art(name, key, job.get("sgdb_id")), "SteamGridDB"
        if not art:
            art, source = store_art(name), "Steam store"
    except Exception as e:
        g["problems"].append(f"art lookup failed: {e}")
    for slot in ("portrait", "banner", "hero", "logo", "icon"):
        url = (art or {}).get(slot)
        if url:
            ext = Path(urllib.parse.urlparse(url).path).suffix or ".png"
            try:
                g["files"][slot] = download(url, work / f"{slot}{ext}")
            except Exception as e:
                g["problems"].append(f"{slot} art download failed: {e}")
    if art and art.get("portrait_png"):
        g["cover"], g["cover_src"] = download(art["portrait_png"], work / f"sgdb_{art['game'][0]}.png"), "SteamGridDB"
    else:
        hit = gamedb_cover(name)
        if hit:
            g["cover"], g["cover_src"] = download(hit[2], work / f"igdb_{hit[0]}.png"), f"IGDB '{hit[1]}'"
    if art:
        g["notes"].append(f"art: {source} '{art['game'][1]}' (id {art['game'][0]}): "
                          f"{', '.join(sorted(g['files'])) or 'none'}")
    else:
        g["skip"] = (f"no confident art match for '{name}'; nothing written. Re-run with --name '<store title>' "
                     "or --sgdb-id <id> (steamgriddb.com/game/<id>)")
    return g


def write_steam(conf, games, dry, problems):
    """All games into every Steam user's shortcuts.vdf + grid art, with a single Steam stop/start."""
    users = steam_users(conf["STEAM_DIR"])
    if not users:
        problems.append("steam: no logged-in Steam user yet - log in once, then re-run")
        return False
    was_running = steam_running()
    if was_running and not dry and not stop_steam(conf["STEAM_DIR"]):
        problems.append("steam: didn't close within 60s; nothing written")
        return False
    for user in users:
        cfg = user / "config"
        vdf = cfg / "shortcuts.vdf"
        sc = read_shortcuts(vdf)
        grid = cfg / "grid"
        art = []
        for g in games:
            _, entry = steam_entry(g["name"], g["launcher"], args=g["info"]["args"])
            stored = upsert_shortcut(sc, g["name"], entry)
            uid = stored["appid"] & 0xFFFFFFFF
            if "icon" in g["files"]:
                stored["icon"] = str(grid / f"{uid}_icon{g['files']['icon'].suffix}")
            art.append((uid, g["files"]))
            if dry:
                print(f"dry-run: steam user {user.name}: {g['name']} -> {uid}")
        if dry:
            continue
        cfg.mkdir(exist_ok=True)
        grid.mkdir(exist_ok=True)
        if vdf.is_file():
            shutil.copy(vdf, vdf.with_suffix(".vdf.bak"))
        write_shortcuts(vdf, sc)
        for uid, files in art:
            for slot, suffix in (("portrait", "p"), ("banner", ""), ("hero", "_hero"), ("logo", "_logo"),
                                 ("icon", "_icon")):
                if slot in files:
                    for old in grid.glob(f"{uid}{suffix}.*"):
                        old.unlink()
                    shutil.copy(files[slot], grid / f"{uid}{suffix}{files[slot].suffix}")
    if was_running and not dry:
        start_steam(conf["STEAM_DIR"])
    return True


def write_apollo(conf, games, dry, problems):
    """All games into apps.json with one elevated write + Apollo restart."""
    apps = read_apps(conf)
    covers = []
    for g in games:
        existing = next((a for a in apps["apps"] if a.get("name") == g["name"]), None)
        apollo_cover = Path(conf["APOLLO_CONFIG"]) / "covers" / g["cover"].name if g["cover"] else None
        if g["cover"]:
            covers.append(g["cover"])
        entry = apollo_entry(g["name"], g["info"], apollo_cover or (existing or {}).get("image-path"),
                             conf["APOLLO_VIRTUAL_DISPLAY"] == "1", existing)
        g["notes"].append(f"apollo: {upsert_app(apps, entry)}")
    if not apply_apollo(conf, apps, covers, dry):
        problems.append("apollo: not written")
        return False
    return True


def cmd_add(args, conf):
    if args.batch:
        jobs = json.loads(Path(args.batch).read_text(encoding="utf-8"))
    elif args.launcher:
        jobs = [{"launcher": args.launcher, "name": args.name, "args": args.args or "", "sgdb_id": args.sgdb_id,
                 "admin": args.admin}]
    else:
        die("give a launcher or --batch <file.json>")
    problems = []
    key, why = sgdb_key(conf)
    if why:
        problems.append(why)
    games = [prepare(job, key) for job in jobs]
    ok = [g for g in games if not g.get("skip")]
    steam_ok = apollo_ok = False
    if ok and not args.no_steam:
        steam_ok = write_steam(conf, ok, args.dry_run, problems)
    if ok and not args.no_apollo:
        apollo_ok = write_apollo(conf, ok, args.dry_run, problems)

    if not key:
        print("note no SteamGridDB key: using Steam store art (no logos/icons)")
    for g in games:
        for n in g["notes"]:
            print("note", f"{g['name']}: {n}" if len(games) > 1 else n)
        for p in g["problems"] + ([g["skip"]] if g.get("skip") else []):
            print("PROBLEM", f"{g['name']}: {p}" if len(games) > 1 else p)
    for p in problems:
        print("PROBLEM", p)
    for g in games:
        if g.get("skip"):
            print(f"{g['name']}: not added")
            continue
        info = g["info"]
        flags = [f for f, on in (("admin", info["admin"]), ("driver-undo", bool(info["services"]))) if on]
        steam = "skip" if args.no_steam else "ok" if steam_ok else "failed"
        apollo = "skip" if args.no_apollo else "ok" if apollo_ok else "failed"
        print(f"{g['name']}: steam={steam} apollo={apollo} cover={g['cover_src'] or 'none'}"
              f"{' [' + ','.join(flags) + ']' if flags else ''}{' (dry-run)' if args.dry_run else ''}"
              f"{' - with problems' if g['problems'] else ''}")
    sys.exit(1 if problems or any(g.get("skip") or g["problems"] for g in games) else 0)


def cmd_list(args, conf):
    for user in steam_users(conf["STEAM_DIR"]):
        for v in read_shortcuts(user / "config" / "shortcuts.vdf").values():
            print(f"steam[{user.name}] {v.get('AppName')}  {v.get('Exe')} {v.get('LaunchOptions', '')}".rstrip())
    for a in read_apps(conf)["apps"]:
        print(f"apollo {a.get('name')}  {a.get('cmd') or ' '.join(a.get('detached', []))}")


def cmd_remove(args, conf):
    found = False
    if not args.no_steam:
        users = steam_users(conf["STEAM_DIR"])
        was_running = steam_running() and not args.dry_run
        if was_running and not stop_steam(conf["STEAM_DIR"]):
            die("steam didn't close within 60s")
        for user in users:
            vdf = user / "config" / "shortcuts.vdf"
            sc = read_shortcuts(vdf)
            hit = [k for k, v in sc.items() if v.get("AppName") == args.name]
            for k in hit:
                uid = sc[k]["appid"] & 0xFFFFFFFF
                found = True
                if not args.dry_run:
                    for f in (user / "config" / "grid").glob(f"{uid}*"):
                        f.unlink()
                del sc[k]
            if hit and not args.dry_run:
                shutil.copy(vdf, vdf.with_suffix(".vdf.bak"))
                write_shortcuts(vdf, sc)
        if was_running:
            start_steam(conf["STEAM_DIR"])
    if not args.no_apollo:
        apps = read_apps(conf)
        before = len(apps["apps"])
        apps["apps"] = [a for a in apps["apps"] if a.get("name") != args.name]
        if len(apps["apps"]) != before:
            found = True
            apply_apollo(conf, apps, [], args.dry_run)
    print(f"{args.name}: {'removed' if found else 'not found'}{' (dry-run)' if args.dry_run else ''}")


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="add-game")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("launcher", nargs="?")
    a.add_argument("--name")
    a.add_argument("--args", help="arguments after the exe, e.g. an emulator's ROM path (needs --name)")
    a.add_argument("--batch", help="JSON list of {launcher, name, args, sgdb_id, admin}: one Steam restart, "
                                   "one UAC prompt")
    a.add_argument("--sgdb-id", type=int)
    a.add_argument("--admin", dest="admin", action="store_true", default=None)
    a.add_argument("--no-admin", dest="admin", action="store_false")
    a.add_argument("--no-steam", action="store_true")
    a.add_argument("--no-apollo", action="store_true")
    a.add_argument("--dry-run", action="store_true")
    sub.add_parser("list")
    r = sub.add_parser("remove")
    r.add_argument("name")
    r.add_argument("--no-steam", action="store_true")
    r.add_argument("--no-apollo", action="store_true")
    r.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    conf = load_conf()
    {"add": cmd_add, "list": cmd_list, "remove": cmd_remove}[args.cmd](args, conf)


if __name__ == "__main__":
    main(sys.argv[1:])
