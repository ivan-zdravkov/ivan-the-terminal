#!/usr/bin/env python3
"""game-graphics: find installed PC games and apply graphics-settings plans to their config files, safely.

  graphics.py scan [--json] [--all]       games from Steam, Epic, GOG, Ubisoft, EA, Battle.net, Xbox and EXTRA_DIRS;
                                          prints new/changed games (--all: every game), upscalers, anti-cheat
  graphics.py peek <file>                 print a game config file (same path rules as apply)
  graphics.py apply <plan.json> [--dry-run]   back up, then write the plan's edits; saves the plan to the overlay
  graphics.py diff <slug>                 what changed in the game's config files since the last backup (learn encodings)
  graphics.py restore <slug> [<stamp>]    put back the files from a backup (default: the newest)
  graphics.py backups [<slug>]
  graphics.py optiscaler latest|status
  graphics.py optiscaler install <game-dir> [--proxy dxgi] [--set Section.Key=Value ...] [--force-offline] [--dry-run]
  graphics.py optiscaler remove <game-dir>
  graphics.py optiscaler update           move every install to the latest stable release, keeping its ini overrides
  graphics.py system [--apply]            Windows: Game Mode, HAGS, windowed optimisations, dGPU per game exe,
                                          RAM speed vs rated (EXPO), iGPU, driver version (--apply: HKCU fixes only)
Config: ~/.config/ivan-the-terminal/game-graphics/config.env (EXTRA_DIRS); plans in .../game-graphics/games/.
State: ~/.local/state/ivan-the-terminal/game-graphics/ (known.json, backups/, optiscaler/, cache/).
Stdlib only. Scans and system checks are Windows-first; plan edits work anywhere.
"""
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

HOME = Path.home()
CONF = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / "ivan-the-terminal/game-graphics"
STATE = Path(os.environ.get("XDG_STATE_HOME") or HOME / ".local/state") / "ivan-the-terminal/game-graphics"
WIN = os.name == "nt"
PROXIES = ("dxgi.dll", "winmm.dll", "version.dll", "dbghelp.dll", "d3d12.dll", "wininet.dll", "winhttp.dll")
OPTI_REPO = "optiscaler/OptiScaler"
CONFIG_EXT = {".ini", ".cfg", ".txt", ".wtf", ".json", ".xml", ".conf", ".toml", ".yaml", ".yml", ".lua", ""}
# Path parts that are never a game's config, even inside an allowed root (browsers, credentials, this setup)
DENY_PARTS = {"microsoft", "google", "mozilla", "bravesoftware", "packages", ".ssh", "sops", ".claude", "claude",
              "ivan-the-terminal", "ivan-the-terrible", "git", "gnupg", "temp", "tmp", "1password", "bitwarden", "discord"}
# Folders under Documents / AppData that hold game configs without naming the game ("My Games\<game>" etc.).
# No launchers (Epic, EA app, Steam, Riot, Battle.net): their folders hold login tokens
PUBLISHERS = {"my games", "saved games", "activision", "ubisoft", "ea games", "ea sports",
              "rockstar games", "cd projekt red", "larian studios", "fromsoftware", "bandai namco", "capcom",
              "square enix", "sega", "bethesda softworks", "bethesda", "playground games", "turn 10 studios",
              "remedy", "io interactive",
              "warner bros. games", "wb games", "paradox interactive", "creative assembly", "2k", "2k games",
              "firaxis games", "naughty dog", "insomniac games", "playstation",
              "nixxes", "kojima productions", "techland", "4a games", "id software", "machinegames", "arkane",
              "obsidian", "frictional games", "hello games", "mojang", "respawn", "eidos montreal", "crytek",
              "warhorse studios", "cdprojektred", "gearbox", "bungie"}
SKIP_EXE = re.compile(r"unins|crash|report|redist|setup|install|vc_?redist|dxweb|quicksfv|helper|launcher_?update|"
                      r"cleaner|broker|attestation|bootstrapper|protocolselector|ue4prereq|dotnet|directx", re.I)
TECH = {  # file name (lower) -> capability; native FSR 3.1+ DLLs are what the driver / OptiScaler can lift to FSR 4
    "amd_fidelityfx_upscaler_dx12.dll": "fsr3.1", "amd_fidelityfx_dx12.dll": "fsr3.1",
    "amd_fidelityfx_loader_dx12.dll": "fsr3.1", "amd_fidelityfx_framegeneration_dx12.dll": "fsr-fg",
    "amd_fidelityfx_vk.dll": "fsr3.1-vk", "ffx_fsr2_api_x64.dll": "fsr2", "ffx_fsr2_api_dx12_x64.dll": "fsr2",
    "nvngx_dlss.dll": "dlss", "nvngx_dlssg.dll": "dlss-fg", "nvngx_dlssd.dll": "dlss-rr", "libxess.dll": "xess",
    "libxess_fg.dll": "xess-fg", "sl.interposer.dll": "streamline", "unityplayer.dll": "unity",
}
ANTICHEAT = re.compile(r"easyanticheat|start_protected_game|beservice|battleye|vgk\.sys|vanguard|xigncode|gameguard|"
                       r"nprotect|eaanticheat|randgrid|secureattestation|pnkbstr|punkbuster|faceit|"
                       r"denuvo-anti-cheat|anticheatexpert|ace-base|mhyprot|equ8|wellbia", re.I)
BLIZZARD_FLAVOURS = {"_retail_": "World of Warcraft", "_classic_": "WoW Classic", "_classic_era_": "WoW Classic Era",
                     "_forever_": "WoW Forever", "_ptr_": "World of Warcraft PTR"}


def out(line):
    print(line, flush=True)


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "game"


def read_env():
    conf = {"EXTRA_DIRS": ""}
    f = CONF / "config.env"
    if f.is_file():
        for line in f.read_text(encoding="utf-8").splitlines():
            m = re.match(r'\s*([A-Z_]+)\s*=\s*"?(.*?)"?\s*(#.*)?$', line)
            if m:
                conf[m.group(1)] = m.group(2)
    return conf


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- inventory

def reg_subkeys(root, path):
    if not WIN:
        return []
    import winreg
    items = []
    try:
        with winreg.OpenKey(root, path) as key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                name = winreg.EnumKey(key, i)
                values = {}
                try:
                    with winreg.OpenKey(key, name) as sub:
                        for j in range(winreg.QueryInfoKey(sub)[1]):
                            k, v, _ = winreg.EnumValue(sub, j)
                            values[k] = v
                except OSError:
                    continue
                items.append((name, values))
    except OSError:
        pass
    return items


def reg_value(root, path, name):
    if not WIN:
        return None
    import winreg
    try:
        with winreg.OpenKey(root, path) as key:
            return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def steam_games():
    roots = []
    if WIN:
        import winreg
        p = reg_value(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath")
        roots.append(Path(p) if p else Path(r"C:\Program Files (x86)\Steam"))
    else:
        roots += [HOME / ".steam/steam", HOME / ".local/share/Steam"]
    libs = []
    for root in roots:
        vdf = root / "steamapps/libraryfolders.vdf"
        if vdf.is_file():
            libs += [Path(p.replace("\\\\", "\\")) for p in
                     re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8", errors="replace"))]
        libs.append(root)
    seen, games = set(), []
    for lib in libs:
        for acf in sorted((lib / "steamapps").glob("appmanifest_*.acf")):
            text = acf.read_text(encoding="utf-8", errors="replace")
            name = re.search(r'"name"\s+"([^"]+)"', text)
            idir = re.search(r'"installdir"\s+"([^"]+)"', text)
            if not (name and idir) or re.search(r"redistributable|proton|steam linux runtime|steamworks", name.group(1), re.I):
                continue
            d = lib / "steamapps/common" / idir.group(1)
            if d not in seen and d.is_dir():
                seen.add(d)
                games.append({"name": name.group(1), "source": "steam", "dir": str(d)})
    return games


def epic_games():
    games = []
    for item in Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "Epic/EpicGamesLauncher/Data/Manifests").glob("*.item"):
        j = load_json(item, {})
        if j.get("InstallLocation") and Path(j["InstallLocation"]).is_dir():
            games.append({"name": j.get("DisplayName") or Path(j["InstallLocation"]).name, "source": "epic",
                          "dir": j["InstallLocation"]})
    return games


def registry_games():
    if not WIN:
        return []
    import winreg
    hk = winreg.HKEY_LOCAL_MACHINE
    games = []
    for _, v in reg_subkeys(hk, r"SOFTWARE\WOW6432Node\GOG.com\Games"):
        if v.get("path") and Path(v["path"]).is_dir():
            games.append({"name": v.get("gameName") or Path(v["path"]).name, "source": "gog", "dir": v["path"]})
    for _, v in reg_subkeys(hk, r"SOFTWARE\WOW6432Node\Ubisoft\Launcher\Installs"):
        d = v.get("InstallDir")
        if d and Path(d).is_dir():
            games.append({"name": Path(d).name, "source": "ubisoft", "dir": str(Path(d))})
    for path in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                 r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
        for _, v in reg_subkeys(hk, path):
            pub, name, loc = v.get("Publisher") or "", v.get("DisplayName") or "", v.get("InstallLocation") or ""
            if "Electronic Arts" in pub and name != "EA app" and loc and Path(loc).is_dir():
                games.append({"name": name, "source": "ea", "dir": str(Path(loc))})
    return games


def blizzard_games():
    games = []
    for base in (os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"), os.environ.get("PROGRAMFILES", r"C:\Program Files")):
        for d in Path(base).glob("*/.build.info"):
            product = d.parent
            flavours = [f for f in product.iterdir() if f.is_dir() and f.name.startswith("_") and f.name.endswith("_")]
            for f in flavours or [product]:
                games.append({"name": BLIZZARD_FLAVOURS.get(f.name, f"{product.name} {f.name.strip('_')}".strip()),
                              "source": "battle.net", "dir": str(f), "online": True})
    return games


def extra_games(conf):
    games = []
    roots = [Path(p) for p in conf.get("EXTRA_DIRS", "").split(";") if p.strip()]
    if WIN:
        roots += [Path(f"{c}:/XboxGames") for c in "CDEFG" if Path(f"{c}:/XboxGames").is_dir()]
    for root in roots:
        if root.is_dir():
            for d in sorted(p for p in root.iterdir() if p.is_dir()):
                games.append({"name": d.name, "source": "xbox" if root.name == "XboxGames" else "folder", "dir": str(d)})
    return games


def walk(top, depth=4):
    top = Path(top)
    base = len(top.parts)
    for root, dirs, files in os.walk(top):
        if len(Path(root).parts) - base >= depth:
            dirs[:] = []
        yield Path(root), dirs, files


def fingerprint(game):
    """Main exe, engine, upscaler DLLs, anti-cheat markers and proxy DLLs, from a shallow walk of the install."""
    exes, tech, ac, proxies = [], set(), set(), {}
    for root, dirs, files in walk(game["dir"]):
        for name in dirs:
            if ANTICHEAT.search(name):
                ac.add(name)
        for name in files:
            low = name.lower()
            if low in TECH:
                tech.add(TECH[low])
            if low.endswith((".exe", ".sys", ".dll")) and ANTICHEAT.search(low):
                ac.add(name)
            if low in PROXIES:
                proxies.setdefault(str(root), []).append(low)
            if low.endswith(".exe") and not SKIP_EXE.search(low):
                p = root / name
                try:
                    exes.append((p.stat().st_size, p))
                except OSError:
                    pass
    exes.sort(reverse=True)
    shipping = [p for _, p in exes if p.name.lower().endswith("-shipping.exe")]
    main = shipping[0] if shipping else (exes[0][1] if exes else None)
    engine = "unreal" if shipping else ("unity" if "unity" in tech else "")
    tech.discard("unity")
    if game.get("source") == "battle.net":
        ac.add("Warden (Blizzard, server-side)")
    st = main.stat() if main else None
    return {**game, "slug": slugify(game["name"]), "exe": str(main) if main else "",
            "exes": [str(p) for _, p in exes[:4]], "engine": engine, "tech": sorted(tech),
            "anticheat": sorted(ac), "proxies": {k: sorted(v) for k, v in proxies.items()},
            "build": f"{st.st_size}:{int(st.st_mtime)}" if st else ""}


def inventory():
    conf = read_env()
    raw = steam_games() + epic_games() + registry_games() + blizzard_games() + extra_games(conf)
    games, seen = [], set()
    for g in raw:
        key = os.path.normcase(os.path.normpath(g["dir"]))
        if key not in seen:
            seen.add(key)
            games.append(fingerprint(g))
    return games


def cmd_scan(args):
    games = inventory()
    known = load_json(STATE / "known.json", {})
    opti = {m["slug"]: m for m in optiscaler_manifests()}
    for g in games:
        k = known.get(g["slug"], {})
        plan = CONF / "games" / f"{g['slug']}.json"
        g["plan"] = str(plan) if plan.is_file() else ""
        g["optiscaler"] = opti.get(g["slug"], {}).get("tag", "")
        g["status"] = ("new" if not g["plan"] else "changed" if k.get("build") and k.get("build") != g["build"]
                       else "planned")
    if "--json" in args:
        print(json.dumps(games, indent=1))
        return 0
    for g in games:
        if g["status"] != "planned" or "--all" in args:
            out(f"{g['status']:8} {g['name']} [{g['source']}] {g['dir']}")
            out(f"         tech={','.join(g['tech']) or '-'} engine={g['engine'] or '-'} "
                f"anticheat={','.join(g['anticheat']) or '-'} optiscaler={g['optiscaler'] or '-'}")
    todo = sum(g["status"] != "planned" for g in games)
    out(f"game-graphics: {len(games)} games, {todo} new or changed")
    return 0


def find_game(slug_or_dir, games=None):
    games = games if games is not None else inventory()
    for g in games:
        if g["slug"] == slug_or_dir:
            return g
    try:
        target = Path(slug_or_dir).resolve()
    except OSError:
        return None
    for g in games:
        d = Path(g["dir"]).resolve()
        if target == d or d in target.parents:
            return g
    return None


# ---------------------------------------------------------------- path safety

def expand(path):
    s = os.path.expandvars(os.path.expanduser(str(path)))
    if WIN:
        s = re.sub(r"%([A-Za-z0-9_()]+)%", lambda m: os.environ.get(m.group(1), m.group(0)), s)
    return Path(s)


def allowed_roots(games):
    roots = [Path(g["dir"]) for g in games]
    roots += [HOME / "Documents", HOME / "Saved Games", HOME / "OneDrive/Documents"]
    if WIN:
        local = Path(os.environ.get("LOCALAPPDATA", HOME / "AppData/Local"))
        roots += [local, local.parent / "LocalLow", Path(os.environ.get("APPDATA", HOME / "AppData/Roaming"))]
    else:
        roots += [HOME / ".local/share/Steam/steamapps/compatdata", HOME / ".steam/steam/steamapps/compatdata"]
    return [r.resolve() for r in roots if r.exists()]


def words(text):
    return {w for w in re.split(r"[^a-z0-9]+", text.lower()) if len(w) >= 4 or w.isdigit()}


def game_folder(name, games):
    """A Documents/AppData folder belongs to games when it is a known publisher folder or shares the significant
    words of a scanned game ("ForzaHorizon6" ~ "Forza Horizon 6", "Assassin's Creed Black Flag Resynced")."""
    low = name.lower()
    if low in PUBLISHERS:
        return True
    squashed = re.sub(r"[^a-z0-9]", "", low)
    for g in games:
        gw = words(g.get("name", "")) - {"game", "games", "edition", "remastered", "definitive"}
        if gw and (len(gw & words(name)) >= min(2, len(gw)) or re.sub(r"[^a-z0-9]", "", g.get("name", "").lower()) == squashed):
            return True
    return False


def check_path(path, games):
    """A game config file: an existing small text file with a config extension, under a scanned game dir or under
    a game's or game publisher's folder in Documents / Saved Games / AppData, never under a browser, credential or
    setup folder. Apps' tokens also live in AppData, and the daily run reads web pages, so `peek` must not reach
    them. Returns (resolved path, problem)."""
    p = expand(path)
    try:
        p = p.resolve(strict=True)
    except OSError:
        return None, f"{path}: does not exist"
    if not p.is_file():
        return None, f"{p}: not a file"
    if p.suffix.lower() not in CONFIG_EXT:
        return None, f"{p}: not a config file type ({p.suffix})"
    roots = allowed_roots(games)
    under = [r for r in roots if r == p or r in p.parents]
    if not under:
        return None, f"{p}: outside game dirs, Documents and AppData"
    rel = p.relative_to(max(under, key=lambda r: len(r.parts))).parts
    game_dir = any(Path(g["dir"]).resolve() in p.parents for g in games)
    if not game_dir:
        if {part.lower() for part in rel[:-1]} & DENY_PARTS:
            return None, f"{p}: inside a protected folder"
        if len(rel) < 2 or not game_folder(rel[0], games):
            return None, f"{p}: {rel[0]} is not a scanned game's or a game publisher's folder"
    if p.stat().st_size > 4 * 1024 * 1024:
        return None, f"{p}: too large for a config file"
    with open(p, "rb") as f:
        head = f.read(65536)
    if b"\0" in head and not head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return None, f"{p}: binary, not a text config"
    return p, ""


def read_text(p):
    raw = Path(p).read_bytes()
    for bom, enc in ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16")):
        if raw.startswith(bom):
            return raw.decode(enc), enc
    return raw.decode("utf-8", errors="surrogateescape"), "utf-8"


def write_text(p, text, enc):
    p = Path(p)
    data = text.encode(enc, errors="surrogateescape" if enc == "utf-8" else "strict")
    ro = WIN and not os.access(p, os.W_OK)
    if ro:
        os.chmod(p, 0o666)
    tmp = p.with_name(p.name + ".gg-tmp")
    tmp.write_bytes(data)
    os.replace(tmp, p)
    if ro:
        os.chmod(p, 0o444)


# ---------------------------------------------------------------- editors (pure: text in, text out)

def nl_of(text):
    return "\r\n" if "\r\n" in text else "\n"


def section_span(lines, section):
    """Line range [start, end) of a section's body; "" = before the first header. (None, None) if missing."""
    header = re.compile(r"\s*\[(.+?)\]\s*$")
    if section == "":
        return 0, next((i for i, l in enumerate(lines) if header.match(l)), len(lines))
    start = None
    for i, line in enumerate(lines):
        m = header.match(line)
        if m and start is not None:
            return start, i
        if m and m.group(1).strip().lower() == section.lower():
            start = i + 1
    return (start, len(lines)) if start is not None else (None, None)


def edit_ini(text, sections):
    """sections: {"Section": {"Key": "value"}}, "" = keys before any section. Keeps comments, order and spacing;
    adds missing keys at the end of their section and missing sections at the end of the file."""
    nl = nl_of(text)
    lines = text.splitlines()
    for section, keys in sections.items():
        start, end = section_span(lines, section)
        if start is None:
            lines += ([""] if lines and lines[-1].strip() else []) + [f"[{section}]"]
            start, end = len(lines), len(lines)
        for key, value in keys.items():
            pat = re.compile(rf"^(\s*{re.escape(key)}\s*=\s*)(.*?)(\s*)$", re.I)
            for i in range(start, end):
                m = pat.match(lines[i])
                if m:
                    lines[i] = f"{m.group(1)}{value}{m.group(3)}"
                    break
            else:
                last = end
                while last > start and not lines[last - 1].strip():
                    last -= 1
                lines.insert(last, f"{key}={value}")
                end += 1
    return nl.join(lines) + (nl if text.endswith(("\n", "\r")) or not text else "")


def edit_wtf(text, keys):
    """WoW Config.wtf: SET name "value"; adds missing names at the end."""
    nl = nl_of(text)
    lines = text.splitlines()
    for key, value in keys.items():
        pat = re.compile(rf'^SET\s+{re.escape(key)}\s+".*"\s*$', re.I)
        for i, line in enumerate(lines):
            if pat.match(line):
                lines[i] = f'SET {key} "{value}"'
                break
        else:
            lines.append(f'SET {key} "{value}"')
    return nl.join(lines) + nl


def edit_cod(text, keys):
    """Call of Duty players/*.txt: `Name@N;h1;h2 = value // one of A, B | lo to hi`. Only existing entries (the
    hashes can't be made up); values are checked against the choices or range in the trailing comment."""
    nl = nl_of(text)
    lines = text.splitlines()
    for key, value in keys.items():
        name = key if "@" in key else f"{key}@0"
        pat = re.compile(rf"^({re.escape(name)};[^=]*=\s*)(.*?)(\s*//\s*(.*))?$")
        for i, line in enumerate(lines):
            m = pat.match(line)
            if not m:
                continue
            hint = m.group(4) or ""
            choices = re.match(r"one of (.+)$", hint)
            rng = re.match(r"(-?[\d.]+) to (-?[\d.]+)$", hint)
            v = str(value)
            if choices and v not in [c.strip() for c in choices.group(1).split(",")]:
                raise ValueError(f"{key}: {v!r} is not one of {choices.group(1)}")
            if rng:
                try:
                    if not float(rng.group(1)) <= float(v) <= float(rng.group(2)):
                        raise ValueError
                except ValueError:
                    raise ValueError(f"{key}: {v!r} is outside {rng.group(1)} to {rng.group(2)}") from None
            lines[i] = f"{m.group(1)}{v}{m.group(3) or ''}"
            break
        else:
            raise ValueError(f"{key}: not in the file (CoD entries can't be added)")
    return nl.join(lines) + nl


def edit_forza(text, keys):
    """Forza UserConfigSelections: <option id="K" value="V"/> first, else an element <K ... value="V"/>."""
    for key, value in keys.items():
        opt = re.compile(rf'(<option\s+id="{re.escape(key)}"\s+value=")[^"]*(")')
        el = re.compile(rf'(<{re.escape(key)}\b[^>]*?\svalue=")[^"]*(")')
        new, n = opt.subn(rf"\g<1>{value}\g<2>", text, count=1)
        if not n:
            new, n = el.subn(rf"\g<1>{value}\g<2>", text, count=1)
        if not n:
            raise ValueError(f"{key}: not in the file")
        text = new
    return text


def edit_json(text, keys):
    """Dotted paths into a JSON object; keeps key order, 2-space indent."""
    data = json.loads(text)
    for key, value in keys.items():
        node, parts = data, key.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


EDITORS = {"ini": edit_ini, "wtf": edit_wtf, "cod": edit_cod, "forza": edit_forza, "json": edit_json}


# ---------------------------------------------------------------- apply / backups

def running_exes():
    if not WIN:
        return set()
    r = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, errors="replace")
    return {line.split('","')[0].strip('"').lower() for line in r.stdout.splitlines() if line}


def backup(slug, files, stamp):
    dest = STATE / "backups" / slug / stamp
    dest.mkdir(parents=True, exist_ok=True)
    manifest = load_json(dest / "manifest.json", {})
    for f in files:
        if str(f) in manifest.values():
            continue
        name = f"{len(manifest):02d}_{Path(f).name}"
        shutil.copy2(f, dest / name)
        manifest[name] = str(f)
    save_json(dest / "manifest.json", manifest)
    stamps = sorted(p for p in (STATE / "backups" / slug).iterdir() if p.is_dir())
    for old in stamps[:-15]:
        shutil.rmtree(old, ignore_errors=True)
    return dest


def cmd_apply(args):
    dry = "--dry-run" in args
    paths = [a for a in args if not a.startswith("--")]
    if not paths:
        sys.exit("usage: graphics.py apply <plan.json> [--dry-run]")
    plan = load_json(paths[0], None)
    if not isinstance(plan, dict) or not plan.get("game"):
        sys.exit(f"game-graphics: {paths[0]} is not a plan (needs at least \"game\")")
    games = inventory()
    slug = plan.get("slug") or slugify(plan["game"])
    game = find_game(slug, games)
    busy = running_exes()
    if game and any(Path(e).name.lower() in busy for e in game["exes"]):
        out(f"PROBLEM {plan['game']} is running: close it first (games rewrite their config on exit)")
        return 1
    problems, changes = [], []
    for e in plan.get("edits", []):
        fmt = e.get("format")
        if fmt not in EDITORS:
            problems.append(f"{e.get('file')}: unknown format {fmt!r} (one of {', '.join(EDITORS)})")
            continue
        p, why = check_path(e.get("file", ""), games)
        if why:
            problems.append(why)
            continue
        text, enc = read_text(p)
        try:
            new = EDITORS[fmt](text, e.get("set", {}))
        except (ValueError, json.JSONDecodeError) as err:
            problems.append(f"{p.name}: {err}")
            continue
        if new != text:
            changes.append((p, new, enc, e))
    for line in problems:
        out(f"PROBLEM {line}")
    if problems:
        out("game-graphics: nothing written (fix the plan and re-run)")
        return 1
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for p, new, enc, e in changes:
        diff = [l for l in difflib.unified_diff(read_text(p)[0].splitlines(), new.splitlines(), lineterm="", n=0)
                if l[:1] in "+-" and not l.startswith(("+++", "---"))]
        out(f"{'would change' if dry else 'changed'} {p} ({len(diff) // 2 or len(diff)} lines)")
        for l in diff[:60]:
            out(f"  {l}")
    if dry:
        out(f"game-graphics: dry run, {len(changes)} files would change")
        return 0
    if changes:
        dest = backup(slug, [p for p, *_ in changes], stamp)
        for p, new, enc, e in changes:
            write_text(p, new, enc)
        out(f"backup: {dest}")
    plan = {**plan, "slug": slug, "applied": stamp if changes else plan.get("applied", stamp)}
    save_json(CONF / "games" / f"{slug}.json", plan)
    known = load_json(STATE / "known.json", {})
    known[slug] = {"build": game["build"] if game else "", "applied": plan["applied"], "name": plan["game"]}
    save_json(STATE / "known.json", known)
    out(f"game-graphics: {plan['game']}: {len(changes)} files changed, plan saved to {CONF / 'games' / (slug + '.json')}")
    return 0


def cmd_peek(args):
    if not args:
        sys.exit("usage: graphics.py peek <file>")
    p, why = check_path(args[0], inventory())
    if why:
        out(f"PROBLEM {why}")
        return 1
    print(read_text(p)[0])
    return 0


def latest_backup(slug, stamp=None):
    base = STATE / "backups" / slug
    stamps = sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []
    if stamp:
        stamps = [s for s in stamps if s.name == stamp]
    return stamps[-1] if stamps else None


def cmd_restore(args):
    if not args:
        sys.exit("usage: graphics.py restore <slug> [<stamp>]")
    b = latest_backup(args[0], args[1] if len(args) > 1 else None)
    if not b:
        out(f"PROBLEM no backup for {args[0]}")
        return 1
    for name, orig in load_json(b / "manifest.json", {}).items():
        shutil.copy2(b / name, orig)
        out(f"restored {orig}")
    out(f"game-graphics: restored {args[0]} from {b.name}")
    return 0


def cmd_backups(args):
    base = STATE / "backups"
    for d in sorted(base.glob(f"{args[0] if args else '*'}/*")):
        out(f"{d.parent.name} {d.name}: {', '.join(Path(v).name for v in load_json(d / 'manifest.json', {}).values())}")
    return 0


def cmd_diff(args):
    if not args:
        sys.exit("usage: graphics.py diff <slug>")
    b = latest_backup(args[0])
    if not b:
        out(f"PROBLEM no backup for {args[0]}: apply a plan first")
        return 1
    plan = load_json(CONF / "games" / f"{args[0]}.json", {})
    edited = {str(expand(e["file"]).resolve()): e for e in plan.get("edits", []) if "file" in e}
    for name, orig in load_json(b / "manifest.json", {}).items():
        if not Path(orig).is_file():
            continue
        cur = read_text(orig)[0].splitlines()
        planned = EDITORS[edited[orig]["format"]](read_text(b / name)[0], edited[orig].get("set", {})).splitlines() \
            if orig in edited else read_text(b / name)[0].splitlines()
        lines = [l for l in difflib.unified_diff(planned, cur, lineterm="", n=0)
                 if l[:1] in "+-" and not l.startswith(("+++", "---"))]
        out(f"{orig}: {len(lines)} lines differ from the applied plan")
        for l in lines[:80]:
            out(f"  {l}")
    return 0


# ---------------------------------------------------------------- OptiScaler

def http_json(url):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "game-graphics"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def opti_latest():
    rel = http_json(f"https://api.github.com/repos/{OPTI_REPO}/releases/latest")
    assets = [a for a in rel.get("assets", []) if a["name"].lower().endswith((".7z", ".zip"))]
    prefix = f"https://github.com/{OPTI_REPO}/releases/download/"
    if not assets or not assets[0]["browser_download_url"].startswith(prefix):
        raise RuntimeError("no OptiScaler archive in the latest release")
    a = assets[0]
    return {"tag": rel["tag_name"], "url": a["browser_download_url"], "name": a["name"],
            "sha256": (a.get("digest") or "").removeprefix("sha256:")}


def seven_zip():
    for c in (shutil.which("7z"), shutil.which("7za"), r"C:\Program Files\7-Zip\7z.exe"):
        if c and Path(c).is_file():
            return [c, "x", "-y"]
    tar = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/tar.exe"  # bsdtar reads 7z
    return [str(tar), "-xf"] if tar.is_file() else None


def opti_fetch(rel):
    cache = STATE / "cache" / rel["tag"]
    x = cache / "x"
    if (x / "OptiScaler.dll").is_file():
        return x
    cache.mkdir(parents=True, exist_ok=True)
    arc = cache / rel["name"]
    req = urllib.request.Request(rel["url"], headers={"User-Agent": "game-graphics"})
    with urllib.request.urlopen(req, timeout=120) as r, open(arc, "wb") as f:
        shutil.copyfileobj(r, f)
    if rel["sha256"] and hashlib.sha256(arc.read_bytes()).hexdigest() != rel["sha256"]:
        arc.unlink()
        raise RuntimeError(f"{rel['name']}: sha256 does not match the release's digest")
    tool = seven_zip()
    if not tool:
        raise RuntimeError("no 7-Zip or tar to unpack the archive")
    x.mkdir(exist_ok=True)
    if tool[1] == "x":
        subprocess.run(tool + [f"-o{x}", str(arc)], check=True, capture_output=True)
    else:
        subprocess.run(tool + [str(arc), "-C", str(x)], check=True, capture_output=True)
    if not (x / "OptiScaler.dll").is_file():  # archives sometimes wrap everything in one folder
        inner = next(x.rglob("OptiScaler.dll"), None)
        if not inner:
            raise RuntimeError("OptiScaler.dll not found in the archive")
        return inner.parent
    return x


def optiscaler_manifests():
    return [load_json(m, {}) for m in sorted((STATE / "optiscaler").glob("*/manifest.json"))]


def opti_target(game):
    """Unreal: the folder of *-Win64-Shipping.exe; else the main exe's folder."""
    return Path(game["exe"]).parent if game.get("exe") else Path(game["dir"])


def parse_sets(args):
    sets = {}
    for i, a in enumerate(args):
        if a == "--set" and i + 1 < len(args):
            k, _, v = args[i + 1].partition("=")
            sec, _, key = k.partition(".")
            sets.setdefault(sec, {})[key] = v
    return sets


def opti_install(game, rel, proxy=None, sets=None, dry=False, force_offline=False, keep_ini=None):
    if game["anticheat"] and not force_offline:
        raise RuntimeError(f"{game['name']} has anti-cheat or is online-only ({', '.join(game['anticheat'])}): "
                           "never inject DLLs here")
    if game.get("online"):
        raise RuntimeError(f"{game['name']} is online-only: never inject DLLs here")
    target = opti_target(game)
    present = {p.name.lower() for p in target.iterdir()}
    man_path = STATE / "optiscaler" / game["slug"] / "manifest.json"
    old = load_json(man_path, {})
    if not proxy:
        proxy = old.get("proxy") or next((n for n in PROXIES if n not in present), None)
    if not proxy or proxy not in PROXIES:
        raise RuntimeError(f"no free proxy DLL name in {target} (all of {', '.join(PROXIES)} exist)")
    if proxy in present and proxy != old.get("proxy"):
        raise RuntimeError(f"{target / proxy} already exists (another mod or loader); pick --proxy from "
                           f"{', '.join(n for n in PROXIES if n not in present)}")
    src = opti_fetch(rel)
    files = [p for p in src.rglob("*") if p.is_file() and not re.search(r"setup_|readme|licen", p.as_posix(), re.I)]
    plan = {}
    for p in files:
        rel_name = p.relative_to(src).as_posix()
        plan[proxy if rel_name == "OptiScaler.dll" else rel_name] = p
    if dry:
        out(f"would install OptiScaler {rel['tag']} into {target} as {proxy} ({len(plan)} files)")
        return 0
    bdir = man_path.parent / "originals"
    backups = dict(old.get("backups", {}))
    installed = set(old.get("files", []))
    ini_dest = target / "OptiScaler.ini"
    for name, p in plan.items():
        dest = target / name
        if name == "OptiScaler.ini" and dest.is_file() and keep_ini is None and name in installed:
            continue  # update without --set: keep the tuned ini
        if dest.exists() and name not in installed and name not in backups:
            (bdir / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dest, bdir / name)
            backups[name] = str(bdir / name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
        installed.add(name)
    overrides = old.get("ini", {})
    for sec, kv in (sets or {}).items():
        overrides.setdefault(sec, {}).update(kv)
    if overrides:
        text, enc = read_text(ini_dest)
        write_text(ini_dest, edit_ini(text, overrides), enc)
    save_json(man_path, {"slug": game["slug"], "name": game["name"], "dir": str(target), "proxy": proxy,
                         "tag": rel["tag"], "files": sorted(installed), "backups": backups, "ini": overrides,
                         "installed": datetime.now().isoformat(timespec="seconds")})
    out(f"installed OptiScaler {rel['tag']} into {target} as {proxy}; in game press Insert for its overlay")
    return 0


def opti_remove(game):
    man_path = STATE / "optiscaler" / game["slug"] / "manifest.json"
    man = load_json(man_path, None)
    if not man:
        out(f"PROBLEM no OptiScaler install recorded for {game['name']}")
        return 1
    target = Path(man["dir"])
    for name in man["files"]:
        (target / name).unlink(missing_ok=True)
    for name, b in man.get("backups", {}).items():
        shutil.copy2(b, target / name)
    for d in sorted({(target / n).parent for n in man["files"]}, key=lambda p: -len(p.parts)):
        if d != target and d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    shutil.rmtree(man_path.parent)
    out(f"removed OptiScaler from {target}; {len(man.get('backups', {}))} original files restored")
    return 0


def cmd_optiscaler(args):
    sub = args[0] if args else "status"
    rest = args[1:]
    if sub == "latest":
        rel = opti_latest()
        out(f"OptiScaler latest stable: {rel['tag']} ({rel['name']})")
        return 0
    if sub == "status":
        mans = optiscaler_manifests()
        for m in mans:
            out(f"{m['name']}: {m['tag']} as {m['proxy']} in {m['dir']}")
        out(f"game-graphics: OptiScaler in {len(mans)} games")
        return 0
    if sub == "update":
        rel, n = opti_latest(), 0
        games = inventory()
        for m in optiscaler_manifests():
            if m["tag"] != rel["tag"]:
                g = find_game(m["slug"], games)
                if g:
                    opti_install(g, rel)
                    n += 1
        out(f"game-graphics: {n} OptiScaler installs moved to {rel['tag']}")
        return 0
    if sub in ("install", "remove") and rest:
        game = find_game(rest[0])
        if not game:
            out(f"PROBLEM {rest[0]} is not a scanned game dir or slug")
            return 1
        if sub == "remove":
            return opti_remove(game)
        proxy = rest[rest.index("--proxy") + 1].lower() if "--proxy" in rest else None
        if proxy and not proxy.endswith(".dll"):
            proxy += ".dll"
        try:
            return opti_install(game, opti_latest(), proxy, parse_sets(rest), "--dry-run" in rest,
                                "--force-offline" in rest, keep_ini=True if "--set" in rest else None)
        except RuntimeError as e:
            out(f"PROBLEM {e}")
            return 1
    sys.exit("usage: graphics.py optiscaler latest|status|update|install <dir> [...]|remove <dir>")


# ---------------------------------------------------------------- system

def ps_json(script):
    r = subprocess.run(["powershell", "-NoProfile", "-Command", f"{script} | ConvertTo-Json -Depth 3 -Compress"],
                       capture_output=True, text=True, errors="replace")
    try:
        data = json.loads(r.stdout or "null")
    except ValueError:
        return []
    return data if isinstance(data, list) else [data] if data else []


def cmd_system(args):
    if not WIN:
        out("game-graphics: system checks are Windows-only")
        return 0
    import winreg
    apply = "--apply" in args
    hkcu, hklm = winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE
    problems, fixed = [], []

    def set_hkcu(path, name, value, kind=winreg.REG_SZ):
        with winreg.CreateKey(hkcu, path) as k:
            winreg.SetValueEx(k, name, 0, kind, value)

    if reg_value(hklm, r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode") != 2:
        problems.append("Hardware-accelerated GPU scheduling is off (Settings > Display > Graphics; needs a reboot)")
    if reg_value(hkcu, r"Software\Microsoft\GameBar", "AutoGameModeEnabled") == 0:
        if apply:
            set_hkcu(r"Software\Microsoft\GameBar", "AutoGameModeEnabled", 1, winreg.REG_DWORD)
            fixed.append("Game Mode on")
        else:
            problems.append("Game Mode is off")
    prefs = r"Software\Microsoft\DirectX\UserGpuPreferences"
    glob = reg_value(hkcu, prefs, "DirectXUserGlobalSettings") or ""
    if "SwapEffectUpgradeEnable=1" not in glob:
        if apply:
            parts = [p for p in glob.split(";") if p and not p.startswith("SwapEffectUpgradeEnable")]
            set_hkcu(prefs, "DirectXUserGlobalSettings", ";".join(parts + ["SwapEffectUpgradeEnable=1"]) + ";")
            fixed.append("windowed-game optimisations on")
        else:
            problems.append("Optimisations for windowed games are off")
    gpus = ps_json("Get-CimInstance Win32_VideoController | Select Name,DriverVersion")
    igpu = [g["Name"] for g in gpus if re.search(r"Radeon\(TM\) Graphics|Intel\(R\) (UHD|Iris)", g.get("Name") or "")]
    dgpu = [g for g in gpus if re.search(r"Radeon RX|GeForce|Arc", g.get("Name") or "")]
    if igpu and dgpu:
        missing = []
        for g in inventory():
            for exe in g["exes"][:2]:
                if (reg_value(hkcu, prefs, exe) or "") != "GpuPreference=2;":
                    missing.append(exe)
        if missing and apply:
            for exe in missing:
                set_hkcu(prefs, exe, "GpuPreference=2;")
            fixed.append(f"{len(missing)} game exes pinned to the dedicated GPU")
        elif missing:
            problems.append(f"iGPU enabled and {len(missing)} game exes not pinned to the dedicated GPU (--apply)")
    ram = ps_json("Get-CimInstance Win32_PhysicalMemory | Select Speed,ConfiguredClockSpeed,PartNumber")
    if ram:
        rated = max(int(r.get("Speed") or 0) for r in ram)
        part = (ram[0].get("PartNumber") or "").strip()
        m = re.search(r"(\d{2})C\d{2}", part)  # e.g. "...64C32...": an EXPO kit rated 6400 whose SPD reports a lower JEDEC speed
        rated = max(rated, int(m.group(1)) * 100) if m and int(m.group(1)) >= 40 else rated
        cur = min(int(r.get("ConfiguredClockSpeed") or 0) for r in ram)
        if cur and rated and cur < rated - 100:
            problems.append(f"RAM runs at {cur} MT/s but is rated {rated}: enable EXPO/XMP in the BIOS (you do this)")
    for line in problems:
        out(f"PROBLEM {line}")
    for line in fixed:
        out(f"fixed {line}")
    drv = ", ".join(f"{g['Name']} {g.get('DriverVersion', '')}" for g in dgpu) or "no dedicated GPU found"
    out(f"game-graphics: system: {len(problems)} problems, {len(fixed)} fixed; {drv}")
    return 0


def main(argv):
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8")
    cmds = {"scan": cmd_scan, "peek": cmd_peek, "apply": cmd_apply, "diff": cmd_diff, "restore": cmd_restore,
            "backups": cmd_backups, "optiscaler": cmd_optiscaler, "system": cmd_system}
    if not argv or argv[0] not in cmds:
        print(__doc__)
        return 2
    return cmds[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
