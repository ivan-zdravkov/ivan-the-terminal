#!/usr/bin/env python3
"""Install and configure the console emulators (Xbox 360: Xenia Canary, PS3: RPCS3, Switch: Eden) around one
emulation folder: ROMs, BIOS/keys/firmware, mods, patches and saves stay there; the emulators point at it.

  emulators.py install [xenia rpcs3 eden]   latest official builds into EMU_DIR/<name> (keeps settings, caches)
  emulators.py setup   [xenia rpcs3 eden]   saves links, keys + firmware, upscaling/fullscreen, patches, mods
  emulators.py status                       versions, links, what still needs a first run
  emulators.py games   [names|systems] [--dry-run]   GAME= entries -> Steam + Apollo (via add-game, one batch)
  emulators.py command <rom>                the emulator command line for a ROM (system from its folder)
  emulators.py pads                         connected XInput pads and the SDL GUIDs Eden binds to
  emulators.py pad desk|stream|<guid>       Eden player 1 -> physical pad / Moonlight's virtual pad (Apollo prep)

Config: ~/.config/ivan-the-terminal/emulators.conf (template: config.example). Problems-only output + one summary.
"""
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

WINDOWS = os.name == "nt"
CONF = Path.home() / ".config" / "ivan-the-terminal" / "emulators.conf"
UA = {"User-Agent": "ivan-the-terminal-emulators/0.1"}
EMULATORS = ("xenia", "rpcs3", "eden")
SYSTEM_EMULATOR = {"xbox360": "xenia", "ps3": "rpcs3", "switch": "eden"}
EXE = {"xenia": "xenia-canary/xenia_canary.exe", "rpcs3": "rpcs3/rpcs3.exe", "eden": "eden/eden.exe"}
# Eden's ResolutionSetup enum: Res1_4X, Res1_2X, Res3_4X, Res1X, Res5_4X, Res3_2X, Res2X, Res3X, Res4X ...
EDEN_SCALES = {"0.25": 0, "0.5": 1, "0.75": 2, "1": 3, "1.25": 4, "1.5": 5, "2": 6, "3": 7, "4": 8}
ZERO_UUID = "0" * 32


def die(msg):
    sys.exit(f"emulators: {msg}")


def load_conf(path=CONF):
    """KEY="value" lines; GAME= may repeat. Paths expand ~ and env vars."""
    conf = {
        "EMULATION_ROOT": "", "EMU_DIR": r"C:\Emulators" if WINDOWS else str(Path.home() / "Emulators"),
        "RES_SCALE": "2", "SWITCH_RES_SCALE": "1.5",
        "SWITCH_MODS": r"60 ?FPS|Stabilize|1920x1080|Disable Dynamic Resolution|Improved Level of Detail",
        "SWITCH_MODS_SKIP": r"Ultrawide|120 ?FPS|Snapshot Quality",
        "SWITCH_USER": os.environ.get("USERNAME") or os.environ.get("USER") or "Player",
        "SWITCH_PROFILE": "", "XENIA_PROFILE": "", "GAME": [],
    }
    if not path.is_file():
        return conf
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r'\s*([A-Z0-9_]+)=("?)(.*?)\2\s*(#.*)?$', line)
        if not m:
            continue
        key, value = m.group(1), os.path.expandvars(m.group(3))
        if key == "GAME":
            conf["GAME"].append(value)
        else:
            conf[key] = value
    return conf


class Paths:
    """Where everything lives. root = the emulation folder, emu = where emulator builds go."""

    def __init__(self, conf):
        if not conf["EMULATION_ROOT"]:
            die(f"EMULATION_ROOT is not set; copy config.example to {CONF}")
        self.root = Path(os.path.expanduser(conf["EMULATION_ROOT"]))
        self.emu = Path(os.path.expanduser(conf["EMU_DIR"]))
        self.roms, self.bios, self.saves = self.root / "roms", self.root / "bios", self.root / "saves"
        self.mods, self.patches = self.root / "mods", self.root / "patches"
        appdata = Path(os.environ.get("APPDATA", Path.home() / ".local/share"))
        self.eden_user = appdata / "eden"

    def exe(self, emu):
        return self.emu / EXE[emu]


# ---------- small helpers ----------
def http_json(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30))


def download(url, dest):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    return Path(dest)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def seven_zip():
    for c in (shutil.which("7z"), shutil.which("7za"), r"C:\Program Files\7-Zip\7z.exe"):
        if c and Path(c).is_file():
            return c
    return None


def extract(archive, dest):
    archive, dest = Path(archive), Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    if archive.suffix.lower() == ".zip":
        with zipfile.ZipFile(archive) as z:
            for n in z.namelist():  # refuse path traversal
                if Path(n).is_absolute() or ".." in Path(n).parts:
                    die(f"{archive.name}: unsafe path {n}")
            z.extractall(dest)
        return
    sz = seven_zip()
    if not sz:
        die(f"7-Zip is needed to extract {archive.name} (winget install 7zip.7zip)")
    out = subprocess.run([sz, "x", "-y", f"-o{dest}", str(archive)], capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    if out.returncode:
        die(f"7-Zip failed on {archive.name}: {out.stderr.strip()[-300:]}")


def is_link(p):
    p = Path(p)
    return p.is_symlink() or (WINDOWS and p.exists() and bool(os.lstat(p).st_file_attributes & 0x400))


def link_dir(link, target):
    """Make `link` a junction (Windows) / symlink to `target`. Returns a problem string or None.
    Never deletes data: an existing non-empty real folder is left alone and reported."""
    link, target = Path(link), Path(target)
    target.mkdir(parents=True, exist_ok=True)
    if is_link(link):
        if Path(os.path.realpath(link)) == Path(os.path.realpath(target)):
            return None
        os.rmdir(link) if WINDOWS else link.unlink()
    elif link.exists():
        if any(link.iterdir()):
            return (f"{link} already holds data; move it into {target} (merge by hand), delete the folder, "
                    "then re-run setup")
        link.rmdir()
    link.parent.mkdir(parents=True, exist_ok=True)
    if WINDOWS:
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)
    return None


def set_ini(text, section, values):
    """Set key=value pairs inside [section] of an INI text, adding the section or keys when missing."""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip() == f"[{section}]"), None)
    if start is None:
        lines += ([""] if lines else []) + [f"[{section}]"] + [f"{k}={v}" for k, v in values.items()]
        return "\n".join(lines) + "\n"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
    todo = dict(values)
    for i in range(start + 1, end):
        k = lines[i].split("=", 1)[0]
        if k in todo:
            lines[i] = f"{k}={todo.pop(k)}"
    insert = [f"{k}={v}" for k, v in todo.items()]
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    lines[end:end] = insert
    return "\n".join(lines) + "\n"


def ini_get(text, section, key):
    cur = None
    for l in text.splitlines():
        if l.startswith("["):
            cur = l.strip()[1:-1]
        elif cur == section and l.split("=", 1)[0] == key:
            return l.split("=", 1)[1]
    return None


def set_toml(text, section, values):
    """Same for the flat TOML Xenia writes ([Section] + `key = value  # comment`)."""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip() == f"[{section}]"), None)
    fmt = {k: (json.dumps(v) if isinstance(v, str) else str(v).lower() if isinstance(v, bool) else str(v))
           for k, v in values.items()}
    if start is None:
        lines += ([""] if lines else []) + [f"[{section}]"] + [f"{k} = {v}" for k, v in fmt.items()]
        return "\n".join(lines) + "\n"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
    for i in range(start + 1, end):
        m = re.match(r"(\s*)([A-Za-z0-9_]+)(\s*=\s*)(.*?)(\s*#.*)?$", lines[i])
        if m and m.group(2) in fmt:
            lines[i] = f"{m.group(1)}{m.group(2)}{m.group(3)}{fmt.pop(m.group(2))}{m.group(5) or ''}"
    lines[end:end] = [f"{k} = {v}" for k, v in fmt.items()]
    return "\n".join(lines) + "\n"


def write_if_changed(path, text):
    path = Path(path)
    old = path.read_text(encoding="utf-8") if path.is_file() else None
    if old == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    if old is not None and not path.with_suffix(path.suffix + ".itt-bak").exists():
        shutil.copy(path, path.with_suffix(path.suffix + ".itt-bak"))  # first-touch backup of the user's file
    path.write_text(text, encoding="utf-8")
    return True


def read_sfo(path):
    """PARAM.SFO -> dict (TITLE_ID, TITLE, APP_VER, ...)."""
    b = Path(path).read_bytes()
    _, _, kt, dt, n = struct.unpack_from("<4sIIII", b, 0)
    out = {}
    for i in range(n):
        ko, fmt, ln, _, do = struct.unpack_from("<HHIII", b, 20 + i * 16)
        k = b[kt + ko:b.index(b"\0", kt + ko)].decode()
        v = b[dt + do:dt + do + ln]
        out[k] = struct.unpack("<I", v[:4])[0] if fmt == 0x0404 else v.rstrip(b"\0").decode("utf-8", "replace")
    return out


def ps3_games(roms):
    """{serial: (folder, sfo)} for disc folders (PS3_GAME/PARAM.SFO) under roms/ps3."""
    games = {}
    for d in sorted(Path(roms).glob("*")):
        sfo = d / "PS3_GAME" / "PARAM.SFO"
        if sfo.is_file():
            s = read_sfo(sfo)
            games[s.get("TITLE_ID", d.name)] = (d, s)
    return games


def switch_profiles(saves):
    """Profile UUIDs that own saves in saves/switch/0000000000000000/<UUID>/ (the NAND user/save layout)."""
    base = Path(saves) / "0000000000000000"
    return sorted(d.name for d in base.glob("*") if re.fullmatch(r"[0-9A-F]{32}", d.name) and d.name != ZERO_UUID) \
        if base.is_dir() else []


def profiles_dat(existing, uuid_hex, username):
    """Eden/yuzu ProfileDataRaw (0x650 bytes: 0x10 pad + 8 x UserRaw 0xC8). The save folder name prints the UUID
    as two u64 (high, low), and the file stores it as little-endian (low, high). Keeps existing users."""
    data = bytearray(existing if existing and len(existing) == 0x650 else bytes(0x650))
    raw = struct.pack("<QQ", int(uuid_hex[16:], 16), int(uuid_hex[:16], 16))
    slots = [0x10 + i * 0xC8 for i in range(8)]
    for i, o in enumerate(slots):
        if data[o:o + 16] == raw:
            return bytes(data), i, False
    free = next((i for i, o in enumerate(slots) if not any(data[o:o + 16])), None)
    if free is None:
        die("Eden already has 8 profiles; remove one in Emulation > Configure > Profiles")
    name = username.encode("utf-8")[:0x20]
    o = slots[free]
    data[o:o + 0xC8] = raw + raw + struct.pack("<Q", 0) + name.ljust(0x20, b"\0") + bytes(0x80)
    return bytes(data), free, True


def switch_rom_tid(name):
    m = re.search(r"\[([0-9A-Fa-f]{16})\]", name)
    return m.group(1).upper() if m else None


def rom_stem(name):
    """'SUPER MARIO ODYSSEY [0100...][v393216][Update v1.4.1].nsp' -> 'supermarioodyssey', to pair updates with games."""
    name = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", Path(name).stem)
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\s+v[\d.]+\s*$", "", name.strip(), flags=re.I).lower())


def nsp_files(path):
    """File names inside an NSP (PFS0 header only)."""
    with open(path, "rb") as f:
        head = f.read(16)
        if head[:4] != b"PFS0":
            return []
        n, size = struct.unpack_from("<II", head, 4)
        entries = [struct.unpack("<QQII", f.read(24)) for _ in range(n)]  # offset, size, name offset, reserved
        names = f.read(size)
    return [names[o:names.index(b"\0", o)].decode("utf-8", "replace") for _, _, o, _ in entries]


def switch_updates(roms, games):
    """Update NSPs in roms for the given game ROM names: [(file, meta NCA id)]. An update's title id ends in 800
    (base game's + 0x800) and comes from the ticket or cert inside, else the file name; it belongs to a game with
    the same base title id or, for ROMs named without one, the same name stem."""
    tids = {switch_rom_tid(g) for g in games} - {None}
    stems = {rom_stem(g) for g in games}
    out = []
    for f in sorted(Path(roms).glob("*.nsp")):
        try:
            files = nsp_files(f)
        except (OSError, struct.error, ValueError):
            continue
        ids = [x[:16].upper() for x in files if re.fullmatch(r"[0-9a-fA-F]{32}\.(tik|cert)", x)]
        tid = (ids or [switch_rom_tid(f.name)])[0]
        meta = next((x.split(".")[0].lower() for x in files if x.endswith(".cnmt.nca")), None)
        if tid and tid.endswith("800") and meta and (tid[:13] + "000" in tids or rom_stem(f.name) in stems):
            out.append((f, meta))
    return out


# ---------- install ----------
def latest(emu):
    """(tag, [(url, filename, sha256 or None)]) of the newest official Windows build."""
    if emu == "xenia":
        r = http_json("https://api.github.com/repos/xenia-canary/xenia-canary-releases/releases/latest")
        a = next(a for a in r["assets"] if re.match(r"xenia_canary_windows.*\.zip$", a["name"]))
        p = http_json("https://api.github.com/repos/xenia-canary/game-patches/releases/latest")
        pa = next(a for a in p["assets"] if a["name"].endswith(".7z"))
        return f"{r['tag_name']}+patches-{p['published_at'][:10]}", [
            (a["browser_download_url"], a["name"], None), (pa["browser_download_url"], pa["name"], None)]
    if emu == "rpcs3":
        r = http_json("https://api.github.com/repos/RPCS3/rpcs3-binaries-win/releases/latest")
        a = next(a for a in r["assets"] if a["name"].endswith("_win64_msvc.7z"))
        sha = next((x for x in r["assets"] if x["name"] == a["name"] + ".sha256"), None)
        digest = None
        if sha:
            digest = urllib.request.urlopen(urllib.request.Request(sha["browser_download_url"], headers=UA),
                                            timeout=30).read().decode().split()[0].lower()
        return a["name"].split("_win64")[0], [(a["browser_download_url"], a["name"], digest)]
    r = http_json("https://git.eden-emu.dev/api/v1/repos/eden-emu/eden/releases/latest")
    a = next(a for a in r["assets"] if re.match(r"Eden-Windows-.*-amd64-clang-pgo\.zip$", a["name"]))
    return r["tag_name"], [(a["browser_download_url"], a["name"], None)]


def cmd_install(args, conf):
    if not WINDOWS:
        die("install fetches the Windows builds; on Linux use the AppImages/Flatpaks")
    p = Paths(conf)
    done, problems = [], []
    for emu in args.emulators or EMULATORS:
        dest = p.exe(emu).parent
        marker = dest / ".itt-version"
        try:
            tag, files = latest(emu)
        except Exception as e:
            problems.append(f"{emu}: release lookup failed: {e}")
            continue
        if marker.is_file() and marker.read_text(encoding="utf-8").strip() == tag and not args.force:
            done.append(f"{emu} {tag} (current)")
            continue
        work = Path(tempfile.mkdtemp(prefix=f"emulators-{emu}-"))
        try:
            for url, name, digest in files:
                f = download(url, work / name)
                if digest and sha256(f) != digest:
                    raise ValueError(f"{name}: sha256 mismatch")
                extract(f, dest)  # over the old build: user data (config, caches, dev_hdd0) is kept
            marker.write_text(tag + "\n", encoding="utf-8")
            done.append(f"{emu} {tag}")
        except Exception as e:
            problems.append(f"{emu}: {e}")
        finally:
            shutil.rmtree(work, ignore_errors=True)
    if "xenia" in (args.emulators or EMULATORS):
        (p.exe("xenia").parent / "portable.txt").touch()  # keep config + cache next to the exe
    for x in problems:
        print("PROBLEM", x)
    print(f"install: {', '.join(done) or 'nothing'} -> {p.emu}{' - with problems' if problems else ''}")
    sys.exit(1 if problems else 0)


# ---------- setup ----------
def setup_xenia(p, conf, notes, problems):
    exe = p.exe("xenia")
    if not exe.is_file():
        return problems.append("xenia: not installed (run install first)")
    home = exe.parent
    (home / "portable.txt").touch()
    saves = p.saves / "xbox360"
    saves.mkdir(parents=True, exist_ok=True)
    profiles = [d.name for d in saves.glob("E0*") if (d / "FFFE07D1").is_dir()]
    xuid = conf["XENIA_PROFILE"] or (profiles[0] if len(profiles) == 1 else "")
    if not xuid and len(profiles) > 1:
        problems.append(f"xenia: several profiles in {saves} ({', '.join(profiles)}); set XENIA_PROFILE")
    scale = int(float(conf["RES_SCALE"]))
    cfg = home / "xenia-canary.config.toml"
    text = cfg.read_text(encoding="utf-8") if cfg.is_file() else ""
    text = set_toml(text, "Storage", {"content_root": str(saves)})  # saves + profiles live in the library
    text = set_toml(text, "GPU", {"draw_resolution_scale_x": scale, "draw_resolution_scale_y": scale,
                                  "vsync": True, "framerate_limit": 60})
    text = set_toml(text, "Display", {"fullscreen": True})
    text = set_toml(text, "General", {"apply_patches": True, "discord": False})
    if xuid:
        text = set_toml(text, "Profiles", {"logged_profile_slot_0_xuid": xuid})
    if write_if_changed(cfg, text):
        notes.append(f"xenia: config {cfg.name} (scale {scale}x, fullscreen, content_root -> {saves})")
    # patches: enable the named ones per title id (XENIA_PATCH_<TITLEID>="name|name")
    for key, want in conf.items():
        m = re.fullmatch(r"XENIA_PATCH_([0-9A-F]{8})", key)
        if not m:
            continue
        files = sorted((home / "patches").glob(f"{m.group(1)} - *.patch.toml"))
        if not files:
            problems.append(f"xenia: no patch file for {m.group(1)} (install fetches game-patches)")
        hit = set()
        for f in files:
            t = f.read_text(encoding="utf-8")
            new = enable_xenia_patches(t, want)
            hit |= {n for n in re.findall(r'^\s*name = "([^"]+)"', t, re.M) if re.fullmatch(want, n)}
            if new != t:
                f.write_text(new, encoding="utf-8")
        notes.append(f"xenia: {m.group(1)} patches on: {', '.join(sorted(hit)) or 'none matched'}")


def enable_xenia_patches(text, want):
    """Set is_enabled = true in each [[patch]] block whose name fully matches the regex `want`
    (others are left as they are, so choices made in Xenia's own patch UI survive)."""
    blocks = re.split(r"(?m)^(?=\s*\[\[patch\]\])", text)
    out = []
    for b in blocks:
        m = re.search(r'(?m)^\s*name = "([^"]+)"', b)
        if m and b.lstrip().startswith("[[patch]]") and re.fullmatch(want, m.group(1)):
            b = re.sub(r"(?m)^(\s*is_enabled = )false", r"\g<1>true", b, count=1)
        out.append(b)
    return "".join(out)


def setup_rpcs3(p, conf, notes, problems):
    exe = p.exe("rpcs3")
    if not exe.is_file():
        return problems.append("rpcs3: not installed (run install first)")
    home = exe.parent
    why = link_dir(home / "dev_hdd0" / "home" / "00000001" / "savedata", p.saves / "ps3")
    if why:
        problems.append(f"rpcs3: {why}")
    trophies = p.saves / "ps3-trophy"
    if trophies.exists():
        why = link_dir(home / "dev_hdd0" / "home" / "00000001" / "trophy", trophies)
        if why:
            problems.append(f"rpcs3: {why}")
    cfg = home / "config" / "config.yml"
    text = cfg.read_text(encoding="utf-8") if cfg.is_file() else ""
    want = {"Video": {"Renderer": "Vulkan", "Resolution Scale": str(int(float(conf["RES_SCALE"]) * 100)),
                      "Anisotropic Filter Override": "16", "Frame limit": "Auto"},
            "Miscellaneous": {"Start games in fullscreen mode": "true", "Exit RPCS3 when process finishes": "true",
                              "Automatically start games after boot": "true"}}
    if write_if_changed(cfg, set_yaml(text, want)):
        notes.append(f"rpcs3: config.yml (resolution {want['Video']['Resolution Scale']}%, fullscreen, auto-exit)")
    games = ps3_games(p.roms / "ps3")
    gy = home / "config" / "games.yml"
    listed = gy.read_text(encoding="utf-8") if gy.is_file() else ""
    add = [f"{s}: {json.dumps(d.as_posix() + '/')}" for s, (d, _) in games.items()
           if not re.search(rf"^{s}:", listed, re.M)]
    if add:
        write_if_changed(gy, listed.rstrip("\n") + ("\n" if listed.strip() else "") + "\n".join(add) + "\n")
        notes.append(f"rpcs3: {len(add)} disc folders added to the game list")
    rpcs3_patches(home, conf, games, notes, problems)
    pad = home / "config" / "input_configs" / "global" / "Default.yml"
    current = pad.read_text(encoding="utf-8") if pad.is_file() else ""
    hand_made = re.search(r"^Player 1 Input:\n  Handler: (?!Null|Keyboard)", current, re.M)
    if not hand_made or "  Device: XInput Pad #" in current:  # keep a pad set up by hand; fix our unquoted one
        write_if_changed(pad, rpcs3_input())
        notes.append("rpcs3: player 1 = XInput Pad #1 (A=Cross, B=Circle, X=Square, Y=Triangle)")
    if not (home / "dev_flash" / "vsh" / "etc" / "version.txt").is_file():
        pup = next(iter(sorted(p.bios.rglob("PS3UPDAT.PUP"))), None)
        problems.append(f'rpcs3: PS3 firmware not installed - run "{exe}" --installfw "{pup or "<PS3UPDAT.PUP>"}"')


def rpcs3_input():
    """RPCS3 input_configs/global/Default.yml: player 1 on the first XInput pad with RPCS3's own XInput defaults
    (same face-button positions as a DualShock 3). Xbox controllers and Moonlight's virtual pad are both XInput."""
    binds = {"Left Stick Left": "LS X-", "Left Stick Down": "LS Y-", "Left Stick Right": "LS X+",
             "Left Stick Up": "LS Y+", "Right Stick Left": "RS X-", "Right Stick Down": "RS Y-",
             "Right Stick Right": "RS X+", "Right Stick Up": "RS Y+", "Start": "Start", "Select": "Back",
             "PS Button": "Guide", "Square": "X", "Cross": "A", "Circle": "B", "Triangle": "Y", "Left": "Left",
             "Down": "Down", "Right": "Right", "Up": "Up", "R1": "RB", "R2": "RT", "R3": "RS", "L1": "LB",
             "L2": "LT", "L3": "LS", "Left Stick Deadzone": 7849, "Right Stick Deadzone": 8689,
             "Left Stick Anti-Deadzone": 4259, "Right Stick Anti-Deadzone": 4259, "Left Trigger Threshold": 30,
             "Right Trigger Threshold": 30}
    lines = ["Player 1 Input:", "  Handler: XInput", '  Device: "XInput Pad #1"', "  Config:"]  # unquoted # = comment
    lines += [f"    {k}: {v}" for k, v in binds.items()]
    return "\n".join(lines) + "\n"


# ---------- controllers ----------
def xinput_pads():
    """Connected XInput pads as [(slot, 'vvvv:pppp', SDL GUID)]. The GUID is built like SDL2's XInput backend
    (bus USB, vendor, product, version, 'x', subtype; the name CRC zeroed as Eden does), so it is what Eden binds to."""
    if not WINDOWS:
        return []
    import ctypes

    class CapsEx(ctypes.Structure):
        _fields_ = [("Type", ctypes.c_ubyte), ("SubType", ctypes.c_ubyte), ("Flags", ctypes.c_ushort),
                    ("Gamepad", ctypes.c_ubyte * 12), ("Vibration", ctypes.c_ushort * 2),
                    ("VendorId", ctypes.c_ushort), ("ProductId", ctypes.c_ushort),
                    ("ProductVersion", ctypes.c_ushort), ("unk1", ctypes.c_ushort), ("unk2", ctypes.c_uint)]

    try:
        dll = ctypes.WinDLL("xinput1_4.dll")
        get = ctypes.WINFUNCTYPE(ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
                                 ctypes.POINTER(CapsEx))((108, dll))  # XInputGetCapabilitiesEx (by ordinal)
    except (OSError, AttributeError):
        return []
    pads = []
    for slot in range(4):
        c = CapsEx()
        if get(1, slot, 0, ctypes.byref(c)) == 0:
            pads.append((slot, f"{c.VendorId:04x}:{c.ProductId:04x}",
                         sdl_xinput_guid(c.VendorId, c.ProductId, c.ProductVersion, c.SubType)))
    return pads


def sdl_xinput_guid(vendor, product, version, subtype=1):
    return (struct.pack("<HHHHHHH", 3, 0, vendor, 0, product, 0, version) + bytes([0x78, subtype])).hex()


# Moonlight/Apollo's virtual pad: ViGEm Xbox 360 (045e:028e, bcdDevice 0x0114)
VIRTUAL_X360 = sdl_xinput_guid(0x045E, 0x028E, 0x0114)


PRO_CONTROLLER, HANDHELD = 0, 4  # Eden's Settings::ControllerType
HANDHELD_SLOT = 8  # players[8] is the console in handheld mode


def eden_pro_controller(guid, slot=0, ctype=PRO_CONTROLLER):
    """Eden [Controls] values for a player on an XInput pad, by button position (Xbox A/bottom -> Switch B,
    B/right -> A, X/left -> Y, Y/top -> X), which is Eden's own SDL default. Slot 0 = player 1."""
    def p(**kw):
        return '"' + ",".join(f"{k}:{v}" for k, v in {"engine": "sdl", "port": 0, "guid": guid, **kw}.items()) + '"'

    n = f"player_{slot}_"
    buttons = {"a": 1, "b": 0, "x": 3, "y": 2, "lstick": 8, "rstick": 9, "l": 4, "r": 5, "plus": 7, "minus": 6,
               "home": 10, "slleft": 4, "srleft": 5, "slright": 4, "srright": 5}
    values = {f"{n}type": str(ctype), f"{n}connected": "true"}
    values.update({f"{n}button_{k}": p(button=v) for k, v in buttons.items()})
    values.update({f"{n}button_d{d}": p(hat=0, direction=d) for d in ("left", "up", "right", "down")})
    values.update({f"{n}button_zl": p(axis=2, threshold=0.5, invert="+"),
                   f"{n}button_zr": p(axis=5, threshold=0.5, invert="+"),
                   f"{n}lstick": p(axis_x=0, axis_y=1, offset_x="0.000000", offset_y="0.000000",
                                   invert_x="+", invert_y="+"),
                   f"{n}rstick": p(axis_x=3, axis_y=4, offset_x="0.000000", offset_y="0.000000",
                                   invert_x="+", invert_y="+")})
    out = {}
    for k, v in values.items():  # Eden ignores a value unless its "\default" flag says it isn't the default
        out[f"{k}\\default"] = "false"
        out[k] = v
    return out


def eden_handheld_game(guid, scale):
    """Per-game sections for a game that refuses the Pro Controller (Let's Go Pikachu/Eevee want one Joy-Con with
    motion when docked): handheld mode, player 1 as Handheld on the same pad, `scale` x the handheld 720p.
    A per-game file only overrides the global controls when it names an input profile."""
    flag = {"\\use_global": "false", "\\default": "false"}
    controls = {"player_0_profile_name": '"itt-handheld"', **eden_pro_controller(guid, 0, HANDHELD)}
    return {"Controls": controls,
            "System": {f"use_docked_mode{k}": v for k, v in flag.items()} | {"use_docked_mode": "0"},
            "Renderer": {f"resolution_setup{k}": v for k, v in flag.items()} | {"resolution_setup": str(scale)}}


def eden_bind_pad(p, guid, conf=None):
    """Bind the pad everywhere Eden reads controls: player 1 + the handheld slot globally, and every
    SWITCH_HANDHELD game's own config."""
    changed = False
    cfg = p.eden_user / "config" / "qt-config.ini"
    text = cfg.read_text(encoding="utf-8") if cfg.is_file() else ""
    text = set_ini(text, "Controls", eden_pro_controller(guid))
    changed |= write_if_changed(cfg, set_ini(text, "Controls", eden_pro_controller(guid, HANDHELD_SLOT, HANDHELD)))
    conf = conf or {}
    scale = EDEN_SCALES.get(conf.get("SWITCH_HANDHELD_RES_SCALE", "2").rstrip("0").rstrip(".") or "1", 6)
    for tid in re.findall(r"[0-9A-Fa-f]{16}", conf.get("SWITCH_HANDHELD", "")):
        game = p.eden_user / "config" / "custom" / f"{tid.upper()}.ini"
        text = game.read_text(encoding="utf-8") if game.is_file() else ""
        for section, values in eden_handheld_game(guid, scale).items():
            text = set_ini(text, section, values)
        changed |= write_if_changed(game, text)
    return changed


def desk_pad(conf):
    """The physical pad's GUID: SWITCH_PAD from the config, else the first connected XInput pad that isn't virtual."""
    if conf.get("SWITCH_PAD"):
        return conf["SWITCH_PAD"]
    return next((g for _, _, g in xinput_pads() if g != VIRTUAL_X360), None)


def cmd_pads(args, conf):
    pads = xinput_pads()
    for slot, ids, guid in pads:
        print(f"xinput {slot + 1}  {ids}  {guid}{'  (Moonlight virtual pad)' if guid == VIRTUAL_X360 else ''}")
    print(f"pads: {len(pads)} connected")


def cmd_pad(args, conf):
    """Point Eden's player 1 at the desk pad, Moonlight's virtual pad (Apollo prep-cmd), or a given GUID."""
    p = Paths(conf)
    guid = {"desk": desk_pad(conf), "stream": conf.get("SWITCH_PAD_STREAM") or VIRTUAL_X360}.get(args.which,
                                                                                               args.which)
    if not guid or not re.fullmatch(r"[0-9a-f]{32}", guid):
        die(f"no pad for '{args.which}': connect it, or set SWITCH_PAD to its GUID (see `pads`)")
    changed = eden_bind_pad(p, guid, conf)
    print(f"pad: Eden player 1 -> {args.which} {guid}{'' if changed else ' (already)'}")


def set_yaml(text, want):
    """Set `Section: / Key: value` pairs in RPCS3's two-level config.yml, keeping everything else."""
    lines = text.splitlines()
    for section, values in want.items():
        start = next((i for i, l in enumerate(lines) if l == f"{section}:"), None)
        if start is None:
            lines += [f"{section}:"] + [f"  {k}: {v}" for k, v in values.items()]
            continue
        end = next((i for i in range(start + 1, len(lines)) if lines[i] and not lines[i].startswith(" ")),
                   len(lines))
        todo = dict(values)
        for i in range(start + 1, end):
            m = re.match(r"  ([^ :][^:]*): ?(.*)$", lines[i])
            if m and m.group(1) in todo:
                lines[i] = f"  {m.group(1)}: {todo.pop(m.group(1))}"
        lines[end:end] = [f"  {k}: {v}" for k, v in todo.items()]
    return "\n".join(lines) + "\n"


def rpcs3_patches(home, conf, games, notes, problems):
    """Fetch the official patch database and enable RPCS3_PATCH_<SERIAL>="name|name" in patch_config.yml."""
    wanted = {k[len("RPCS3_PATCH_"):]: v for k, v in conf.items() if k.startswith("RPCS3_PATCH_")}
    if not wanted:
        return
    db = home / "patches" / "patch.yml"
    try:
        j = http_json("https://rpcs3.net/compatibility?patch&api=v1&v=1.2")
        if hashlib.sha256(j["patch"].encode("utf-8")).hexdigest() != j["sha256"]:
            raise ValueError("checksum mismatch")
        write_if_changed(db, j["patch"])
    except Exception as e:
        problems.append(f"rpcs3: patch database download failed ({e}); using {db.name if db.is_file() else 'none'}")
    if not db.is_file():
        return
    enable = {}  # hash -> patch -> title -> serial -> [versions]
    cur_hash = cur_patch = title = None
    for line in db.read_text(encoding="utf-8").splitlines():
        if re.match(r"^(PPU|SPU)-[0-9a-f]+:", line):
            cur_hash = line[:-1]
        elif m := re.match(r'^  (?! )"?(.+?)"?:\s*$', line):
            cur_patch = m.group(1)
        elif m := re.match(r'^      (?! )"?(.+?)"?:\s*$', line):
            title = m.group(1)
        elif (m := re.match(r"^        ([A-Z]{4}\d{5}): \[(.*)\]", line)) and cur_hash and m.group(1) in wanted:
            if re.fullmatch(wanted[m.group(1)], cur_patch):
                versions = [v.strip() for v in m.group(2).split(",")]
                enable.setdefault(cur_hash, {}).setdefault(cur_patch, {}).setdefault(title, {})[m.group(1)] = versions
    out = []
    for h, patches in enable.items():
        out.append(f"{h}:")
        for name, titles in patches.items():
            out.append(f"  {json.dumps(name)}:")
            for t, serials in titles.items():
                out.append(f"    {json.dumps(t)}:")
                for s, versions in serials.items():
                    out.append(f"      {s}:")
                    for v in versions:
                        out += [f"        {json.dumps(v)}:", "          Enabled: true"]
    if write_if_changed(home / "config" / "patch_config.yml", "\n".join(out) + "\n"):
        pass
    on = sorted({f"{s} {n}" for ps in enable.values() for n, ts in ps.items() for ss in ts.values() for s in ss})
    notes.append(f"rpcs3: patches on: {', '.join(on) or 'none matched'}")
    for serial in wanted:
        if serial not in games:
            problems.append(f"rpcs3: RPCS3_PATCH_{serial} names a game that isn't in {Path('roms/ps3')}")


def setup_eden(p, conf, notes, problems):
    if not p.exe("eden").is_file():
        return problems.append("eden: not installed (run install first)")
    user = p.eden_user
    saves = p.saves / "switch"
    why = link_dir(user / "nand" / "user" / "save", saves)
    if why:
        problems.append(f"eden: {why}")
    # profile: the UUID that owns the saves, so Eden opens them instead of making a new random user
    uuids = [conf["SWITCH_PROFILE"]] if conf["SWITCH_PROFILE"] else switch_profiles(saves)
    user_index = None
    if len(uuids) > 1:
        problems.append(f"eden: several profiles own saves ({', '.join(uuids)}); set SWITCH_PROFILE")
    elif uuids:
        dat = user / "nand" / "system" / "save" / "8000000000000010" / "su" / "avators" / "profiles.dat"
        data, user_index, changed = profiles_dat(dat.read_bytes() if dat.is_file() else None, uuids[0],
                                                 conf["SWITCH_USER"])
        if changed:
            dat.parent.mkdir(parents=True, exist_ok=True)
            dat.write_bytes(data)
            notes.append(f"eden: profile {uuids[0]} ({conf['SWITCH_USER']}) registered")
    # keys + firmware from the BIOS folder
    keys = sorted(p.bios.rglob("prod.keys"))
    if not keys:
        problems.append(f"eden: no prod.keys under {p.bios}")
    else:
        for k in ("prod.keys", "title.keys"):
            src = keys[0].parent / k
            if src.is_file() and (not (user / "keys" / k).is_file() or sha256(src) != sha256(user / "keys" / k)):
                (user / "keys").mkdir(parents=True, exist_ok=True)
                shutil.copy(src, user / "keys" / k)
                notes.append(f"eden: {k} copied")
    fw = sorted(p.bios.rglob("Firmware*.zip"), key=lambda f: [int(x) for x in re.findall(r"\d+", f.name)])
    registered = user / "nand" / "system" / "Contents" / "registered"
    marker = registered / ".itt-firmware"
    if not fw:
        problems.append(f"eden: no Firmware*.zip under {p.bios}")
    elif not marker.is_file() or marker.read_text(encoding="utf-8").strip() != fw[-1].name:
        registered.mkdir(parents=True, exist_ok=True)
        for old in registered.glob("*.nca"):
            old.unlink()
        extract(fw[-1], registered)
        marker.write_text(fw[-1].name + "\n", encoding="utf-8")
        notes.append(f"eden: firmware {fw[-1].stem} installed")
    # mods: chosen sub-folders of mods/switch/<Game> [<TitleID>][mods]/ -> load/<TitleID>/
    inc, skip = re.compile(conf["SWITCH_MODS"], re.I), re.compile(conf["SWITCH_MODS_SKIP"], re.I)
    for game in sorted((p.mods / "switch").glob("*")):
        tid = switch_rom_tid(game.name)
        if not tid or not game.is_dir():
            continue
        dest, chosen = user / "load" / tid, []
        managed = dest / ".itt-mods"
        before = set(managed.read_text(encoding="utf-8").split("\n")) - {""} if managed.is_file() else set()
        for mod in sorted(d for d in game.iterdir() if d.is_dir()):
            if inc.search(mod.name) and not skip.search(mod.name):
                chosen.append(mod.name)
                if not (dest / mod.name).is_dir() or mod.name not in before:
                    shutil.copytree(mod, dest / mod.name, dirs_exist_ok=True)
        for gone in before - set(chosen):
            shutil.rmtree(dest / gone, ignore_errors=True)
        if chosen or before:
            dest.mkdir(parents=True, exist_ok=True)
            managed.write_text("\n".join(chosen) + "\n", encoding="utf-8")
        if set(chosen) != before:
            notes.append(f"eden: {game.name.split(' [')[0]} mods: {', '.join(chosen) or 'none'}")
    # updates: from the game folder Eden takes only their data (RomFS), not the code (ExeFS), so the base game's
    # code runs on newer data - crashes and hangs. Installed to NAND, both load.
    nand = user / "nand" / "user" / "Contents" / "registered"
    installed = {f.name.split(".")[0].lower() for f in nand.rglob("*.nca")} if nand.is_dir() else set()
    games = [g.split("|")[1].strip() for g in conf["GAME"] if g.split("|")[0].strip() == "switch" and "|" in g]
    missing = [f.name for f, meta in switch_updates(p.roms / "switch", games) if meta not in installed]
    if missing:
        problems.append(f"eden: updates not installed (the base game's code would run on the update's data): "
                        f"{'; '.join(missing)} - in Eden: File > Install Files to NAND, then re-run setup")
    # config: internal resolution, ROM folder in the game list (DLC there loads without installing)
    cfg = user / "config" / "qt-config.ini"
    text = cfg.read_text(encoding="utf-8") if cfg.is_file() else ""
    scale = EDEN_SCALES.get(conf["SWITCH_RES_SCALE"].rstrip("0").rstrip(".") or "1")
    if scale is None:
        problems.append(f"eden: SWITCH_RES_SCALE {conf['SWITCH_RES_SCALE']} isn't one of {', '.join(EDEN_SCALES)}")
    else:
        text = set_ini(text, "Renderer", {"resolution_setup\\default": "false", "resolution_setup": str(scale)})
    text = set_ini(text, "System", {"use_docked_mode\\default": "false", "use_docked_mode": "1"})
    if user_index is not None:  # boot games as the profile that owns the saves
        text = set_ini(text, "System", {"current_user\\default": str(user_index == 0).lower(),
                                        "current_user": str(user_index)})
    text = set_ini(text, "Data%20Storage", {"ext_content_from_game_dirs\\default": "false",
                                            "ext_content_from_game_dirs": "true"})
    text = add_game_dir(text, (p.roms / "switch").as_posix())
    if write_if_changed(cfg, text):
        notes.append(f"eden: qt-config.ini (docked, {conf['SWITCH_RES_SCALE']}x, game dir {p.roms / 'switch'})")
    pad = desk_pad(conf)
    if not pad:
        problems.append("eden: no controller to bind - connect the pad (or set SWITCH_PAD) and re-run setup")
    elif needs_pad_binding(text, pad) or conf.get("SWITCH_HANDHELD"):
        if eden_bind_pad(p, pad, conf):
            notes.append(f"eden: player 1 = Pro Controller on {pad} (buttons by position)"
                         + (f"; handheld for {conf['SWITCH_HANDHELD']}" if conf.get("SWITCH_HANDHELD") else ""))


def needs_pad_binding(text, pad):
    """Bind when player 1 has no mapping or is on another SDL pad (e.g. left on Moonlight's after a stream);
    a hand-made non-SDL mapping (keyboard) is kept."""
    if "player_0_button_a=" not in text:
        return True
    bound = re.search(r"^player_0_button_a=.*guid:([0-9a-f]{32})", text, re.M)
    return bool(bound) and bound.group(1) != pad


def add_game_dir(text, path):
    """Eden's [UI] Paths\\gamedirs array (1-based); SDMC/UserNAND/SysNAND first, as Eden writes it itself."""
    size = int(ini_get(text, "UI", "Paths\\gamedirs\\size") or 0)
    dirs = [ini_get(text, "UI", f"Paths\\gamedirs\\{i}\\path") for i in range(1, size + 1)]
    if path in dirs:
        return text
    values = {}
    if not size:
        dirs = ["SDMC", "UserNAND", "SysNAND"]
        for i, d in enumerate(dirs, 1):
            values.update({f"Paths\\gamedirs\\{i}\\deep_scan": "false", f"Paths\\gamedirs\\{i}\\expanded": "true",
                           f"Paths\\gamedirs\\{i}\\path": d})
    n = len(dirs) + 1
    values.update({f"Paths\\gamedirs\\{n}\\deep_scan": "false", f"Paths\\gamedirs\\{n}\\expanded": "true",
                   f"Paths\\gamedirs\\{n}\\path": path, "Paths\\gamedirs\\size": str(n)})
    return set_ini(text, "UI", values)


def cmd_setup(args, conf):
    p = Paths(conf)
    notes, problems = [], []
    for emu in args.emulators or EMULATORS:
        {"xenia": setup_xenia, "rpcs3": setup_rpcs3, "eden": setup_eden}[emu](p, conf, notes, problems)
    for n in notes:
        print("note", n)
    for x in problems:
        print("PROBLEM", x)
    print(f"setup: {', '.join(args.emulators or EMULATORS)} - {len(notes)} change(s)"
          f"{', ' + str(len(problems)) + ' problem(s)' if problems else ''}")
    sys.exit(1 if problems else 0)


# ---------- status ----------
def cmd_status(args, conf):
    p = Paths(conf)
    links = {"xenia": None, "rpcs3": p.exe("rpcs3").parent / "dev_hdd0/home/00000001/savedata",
             "eden": p.eden_user / "nand/user/save"}
    problems = []
    for emu in EMULATORS:
        exe = p.exe(emu)
        ver = (exe.parent / ".itt-version").read_text(encoding="utf-8").strip() \
            if (exe.parent / ".itt-version").is_file() else ("installed" if exe.is_file() else "MISSING")
        link = links[emu]
        saves = (f"saves -> {os.path.realpath(link)}" if link and is_link(link)
                 else "saves: content_root" if emu == "xenia" else "saves NOT linked")
        print(f"{emu:6} {ver:40} {saves}")
        if ver == "MISSING" or "NOT" in saves:
            problems.append(emu)
    if p.exe("rpcs3").is_file() and not (p.exe("rpcs3").parent / "dev_flash/vsh/etc/version.txt").is_file():
        print("rpcs3  PS3 firmware not installed (see setup)")
        problems.append("rpcs3 firmware")
    print(f"status: {len(EMULATORS) - len(problems)}/{len(EMULATORS)} ready" if not problems
          else f"status: needs attention: {', '.join(problems)}")


# ---------- games ----------
def command(p, rom):
    """(exe, args) launching `rom` fullscreen in the emulator for its system (roms/<system>/...)."""
    rom = Path(rom)
    try:
        system = rom.resolve().relative_to(p.roms.resolve()).parts[0]
    except ValueError:
        die(f"{rom} is not under {p.roms}")
    emu = SYSTEM_EMULATOR.get(system) or die(f"no emulator set up for '{system}'")
    if emu == "rpcs3":
        eboot = rom / "PS3_GAME" / "USRDIR" / "EBOOT.BIN" if rom.is_dir() else rom
        return p.exe(emu), f'--no-gui "{eboot}"'
    if emu == "eden":
        return p.exe(emu), f'-f -g "{rom}"'
    return p.exe(emu), f'"{rom}"'


def cmd_command(args, conf):
    exe, a = command(Paths(conf), args.rom)
    print(f'"{exe}" {a}')


def cmd_games(args, conf):
    p = Paths(conf)
    jobs, problems = [], []
    for g in conf["GAME"]:
        parts = [x.strip() for x in g.split("|")]
        if len(parts) < 3:
            problems.append(f"GAME={g!r}: expected system|rom|name[|sgdb-id]")
            continue
        system, rom, name = parts[:3]
        if args.names and name not in args.names and system not in args.names:
            continue
        path = p.roms / system / rom
        if not path.exists():
            problems.append(f"{name}: {path} not found")
            continue
        exe, a = command(p, path)
        job = {"launcher": str(exe), "name": name, "args": a}
        if SYSTEM_EMULATOR.get(system) == "eden":  # Eden binds pads by GUID: use Moonlight's pad while streaming
            me = f'"{sys.executable}" -I "{Path(__file__).resolve()}"'
            job["prep"] = [{"do": f"{me} pad stream", "undo": f"{me} pad desk"}]
        if len(parts) > 3 and parts[3]:
            job["sgdb_id"] = int(parts[3])
        jobs.append(job)
    for x in problems:
        print("PROBLEM", x)
    if not jobs:
        die("no games to add (GAME= lines in emulators.conf)")
    batch = Path(tempfile.mkdtemp(prefix="emulators-games-")) / "games.json"
    batch.write_text(json.dumps(jobs, indent=1), encoding="utf-8")
    addgame = Path(__file__).resolve().parents[2] / "add-game" / "scripts" / "addgame.py"
    cmd = [sys.executable, str(addgame), "add", "--batch", str(batch)] + (["--dry-run"] if args.dry_run else [])
    sys.exit(subprocess.run(cmd).returncode or (1 if problems else 0))


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="emulators")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("install", "setup"):
        s = sub.add_parser(name)
        s.add_argument("emulators", nargs="*", metavar="{xenia,rpcs3,eden}")
        if name == "install":
            s.add_argument("--force", action="store_true")
    sub.add_parser("status")
    g = sub.add_parser("games")
    g.add_argument("names", nargs="*", help="only these GAME names or systems (default: all)")
    g.add_argument("--dry-run", action="store_true")
    c = sub.add_parser("command")
    c.add_argument("rom")
    sub.add_parser("pads")
    pd = sub.add_parser("pad")
    pd.add_argument("which", help="desk | stream | <SDL GUID>")
    args = ap.parse_args(argv)
    unknown = [e for e in getattr(args, "emulators", []) if e not in EMULATORS]
    if unknown:
        ap.error(f"unknown emulator(s) {', '.join(unknown)}; choose from {', '.join(EMULATORS)}")
    conf = load_conf()
    {"install": cmd_install, "setup": cmd_setup, "status": cmd_status, "games": cmd_games,
     "command": cmd_command, "pads": cmd_pads, "pad": cmd_pad}[args.cmd](args, conf)


if __name__ == "__main__":
    main(sys.argv[1:])
