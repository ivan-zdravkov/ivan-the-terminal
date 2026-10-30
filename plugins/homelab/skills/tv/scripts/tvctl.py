#!/usr/bin/env python3
"""tvctl: keep an Android / Google TV's sideloaded apps current and its settings in place, over adb.

  tvctl.py status [--json]                     apps (installed vs latest), autostart, always-on VPN
  tvctl.py update [APP...] [--dry-run]         install missing / update outdated apps from their official sources
              [--weekly] [--notify]            timer mode: at most once per WEEKLY_DAYS, skip apps in use, notify
  tvctl.py setup                               autostart app on boot, always-on VPN, disabled stock apps (idempotent)
  tvctl.py connect                             adb connect (TV_ADB, else mDNS discovery)

Config: ~/.config/ivan-the-terminal/tv.conf (template: ../config.example). Stdlib only.
Prints problems only as "LEVEL check detail" plus a summary line; exit 1 on any fail.
"""
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CONF = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "ivan-the-terminal/tv.conf"
STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "ivan-the-terminal/tv"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "ivan-the-terminal/tv"
UA = {"User-Agent": "ivan-the-terminal-tv/1"}


def http(url, as_json=False):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        body = r.read()
    return json.loads(body) if as_json else body.decode()


def vtuple(s):
    m = re.search(r"\d+(?:\.\d+)*", s or "")
    return tuple(int(x) for x in m.group().split(".")) if m else ()


# --- official sources: each returns (version, url, sha256 or None) for the device ABIs

def stremio_page_latest(html, abis):
    found = re.findall(r"https://dl\.strem\.io/android/v(\d+(?:\.\d+)+)-androidTV/com\.stremio\.one-\1-\d+-([\w-]+)\.apk", html)
    for abi in abis:
        best = max((v for v, a in found if a == abi), key=vtuple, default=None)
        if best:
            url = re.search(rf"https://dl\.strem\.io/android/v{re.escape(best)}-androidTV/com\.stremio\.one-"
                            rf"{re.escape(best)}-\d+-{re.escape(abi)}\.apk", html).group()
            return best, url, None
    raise LookupError(f"no stable Android TV build for {abis} on stremio.com/downloads")


def stremio(abis):
    return stremio_page_latest(http("https://www.stremio.com/downloads"), abis)


def stremio_boot(abis):
    # Official "Launch on Boot" helper: unversioned URL, so it's installed when missing and otherwise left alone.
    return None, "https://dl.strem.io/android/StremioLaunchOnBoot.apk", None


def smarttube(abis):
    rel = http("https://api.github.com/repos/yuliskov/SmartTube/releases/latest", as_json=True)
    assets = {a["name"]: a for a in rel["assets"]}
    for abi in [*abis, "universal"]:
        for name, a in assets.items():
            m = re.fullmatch(rf"SmartTube_stable_([\d.]+)_{re.escape(abi)}\.apk", name)
            if m:
                return m.group(1), a["browser_download_url"], (a.get("digest") or "").removeprefix("sha256:") or None
    raise LookupError(f"no SmartTube stable asset for {abis} in {rel['tag_name']}")


def tailscale(abis):
    idx = http("https://pkgs.tailscale.com/stable/?mode=json", as_json=True)
    url = f"https://pkgs.tailscale.com/stable/{idx['APKs']['universal']}"
    return idx["APKsVersion"], url, http(url + ".sha256").split()[0]


APPS = {
    "stremio": ("com.stremio.one", stremio),
    "stremio-boot": ("com.stremio.tv.launcher", stremio_boot),
    "smarttube": ("org.smarttube.stable", smarttube),
    "tailscale": ("com.tailscale.ipn", tailscale),
}
VPN_PKGS = {"tailscale": "com.tailscale.ipn"}
BOOT_HELPERS = {"stremio": ("com.stremio.tv.launcher", "com.stremio.tv.launcher/.MainActivity")}


def load_conf():
    conf = {"TV_ADB": "", "APPS": "stremio stremio-boot smarttube tailscale",
            "AUTOSTART": "stremio", "ALWAYS_ON_VPN": "tailscale", "DISABLE": "", "WEEKLY_DAYS": "7"}
    if CONF.is_file():
        for line in CONF.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                conf[key.strip()] = " ".join(shlex.split(value, comments=True))
    unknown = set(conf["APPS"].split()) - APPS.keys()
    if unknown:
        sys.exit(f"tv: unknown APPS in {CONF}: {' '.join(sorted(unknown))} (known: {' '.join(APPS)})")
    return conf


class TV:
    def __init__(self, serial):
        self.serial = serial

    def adb(self, *args, timeout=60):
        return subprocess.run(["adb", "-s", self.serial, *args], capture_output=True, text=True, timeout=timeout)

    def sh(self, cmd):
        return self.adb("shell", cmd).stdout.strip()

    def version(self, pkg):
        m = re.search(r"versionName=(\S+)", self.sh(f"dumpsys package {pkg} | grep -m1 versionName"))
        return m.group(1) if m else None

    def abis(self):
        return self.sh("getprop ro.product.cpu.abilist").split(",")

    def foreground(self):
        if "mWakefulness=Awake" not in self.sh("dumpsys power | grep mWakefulness="):
            return None
        m = re.search(r"u0 ([\w.]+)/", self.sh("dumpsys activity activities | grep -m1 mResumedActivity"))
        return m.group(1) if m else None


def connect(conf):
    """TV_ADB first; if it's empty or stale (DHCP moved the TV), the single adb device mDNS advertises."""
    candidates = [conf["TV_ADB"]] if conf["TV_ADB"] else []
    res = subprocess.run(["adb", "mdns", "services"], capture_output=True, text=True, timeout=30).stdout
    hits = re.findall(r"_adb\._tcp\.?\s+([\d.]+:\d+)", res)
    if len(hits) == 1 and hits[0] not in candidates:
        candidates.append(hits[0])
    for target in candidates:
        subprocess.run(["adb", "connect", target], capture_output=True, text=True, timeout=30)
        state = subprocess.run(["adb", "-s", target, "get-state"], capture_output=True, text=True, timeout=30)
        if state.stdout.strip() == "device":
            if target != conf["TV_ADB"]:
                print(f"tv: reached the TV at {target} via mDNS; update TV_ADB in {CONF}", file=sys.stderr)
            return TV(target)
    return None


def plan(tv, names):
    abis = tv.abis()
    rows = []
    for name in names:
        pkg, source = APPS[name]
        installed = tv.version(pkg)
        try:
            latest, url, sha = source(abis)
        except Exception as e:  # network or page change: report, keep going
            rows.append(dict(app=name, pkg=pkg, installed=installed, latest=None, state="unknown", detail=str(e)))
            continue
        if installed is None:
            state = "missing"
        elif latest and vtuple(latest) > vtuple(installed):
            state = "outdated"
        else:
            state = "current"
        rows.append(dict(app=name, pkg=pkg, installed=installed, latest=latest, url=url, sha256=sha, state=state))
    return rows


def fetch(url, sha):
    CACHE.mkdir(parents=True, exist_ok=True)
    dest = CACHE / url.rsplit("/", 1)[1]
    h = hashlib.sha256()
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600) as r, open(dest, "wb") as f:
        while chunk := r.read(1 << 20):
            h.update(chunk)
            f.write(chunk)
    if sha and h.hexdigest() != sha.lower():
        dest.unlink()
        raise ValueError(f"sha256 mismatch for {url}")
    return dest


def install(tv, row):
    apk = fetch(row["url"], row.get("sha256"))
    try:
        res = tv.adb("install", "-r", str(apk), timeout=900)
    finally:
        apk.unlink(missing_ok=True)
    out = (res.stdout + res.stderr).strip().splitlines()
    if res.returncode != 0 or not out or out[-1] != "Success":
        raise RuntimeError(out[-1] if out else f"adb install exit {res.returncode}")


def setup_checks(tv, conf, apply):
    """Yield (level, check, detail); with apply=True fix what can be fixed over adb first."""
    for name in conf["AUTOSTART"].split():
        pkg, activity = BOOT_HELPERS[name]
        if tv.version(pkg) is None:
            yield "warn", f"autostart:{name}", f"boot helper {pkg} not installed (add {name}-boot to APPS, run update)"
            continue
        if apply:
            tv.sh(f"appops set {pkg} SYSTEM_ALERT_WINDOW allow")
            if "stopped=true" in tv.sh(f"dumpsys package {pkg} | grep -m1 stopped="):
                tv.sh(f"am start -W -n {activity}")  # first launch lifts the stopped state so BOOT_COMPLETED arrives
                time.sleep(2)
                tv.sh("input keyevent KEYCODE_HOME")
        ops = tv.sh(f"appops get {pkg} SYSTEM_ALERT_WINDOW")
        stopped = "stopped=true" in tv.sh(f"dumpsys package {pkg} | grep -m1 stopped=")
        if "allow" not in ops or stopped:
            yield "fail", f"autostart:{name}", "helper can't start on boot: run `itt run tv setup`"
        else:
            yield "ok", f"autostart:{name}", "starts on boot"
    vpn = conf["ALWAYS_ON_VPN"]
    if vpn:
        pkg = VPN_PKGS[vpn]
        if tv.version(pkg) is None:
            yield "warn", "vpn", f"{vpn} not installed"
            return
        if apply:
            tv.sh(f"appops set {pkg} ACTIVATE_VPN allow")
            tv.sh(f"settings put secure always_on_vpn_app {pkg}; settings put secure always_on_vpn_lockdown 0")
        if tv.sh("settings get secure always_on_vpn_app") != pkg:
            yield "fail", "vpn", f"{vpn} is not the always-on VPN: run `itt run tv setup`"
        elif "VPN" not in tv.sh("dumpsys connectivity | grep -m1 -E 'NetworkAgentInfo.*VPN'"):
            yield "warn", "vpn", f"{vpn} not connected: log in on the TV (open the app, scan the QR code)"
        else:
            yield "ok", "vpn", f"{vpn} always-on and connected"
    # Stock apps to keep disabled (firmware and Play Store updates can re-enable them); `pm enable` undoes it.
    disabled = set(re.findall(r"package:(\S+)", tv.sh("pm list packages -d")))
    for pkg in conf["DISABLE"].split():
        if apply and pkg not in disabled and tv.version(pkg) is not None:
            tv.sh(f"pm disable-user --user 0 {shlex.quote(pkg)}")
            disabled = set(re.findall(r"package:(\S+)", tv.sh("pm list packages -d")))
        if pkg in disabled or tv.version(pkg) is None:
            yield "ok", f"disabled:{pkg}", "disabled"
        else:
            yield "warn", f"disabled:{pkg}", "enabled again: run `itt run tv setup`"


def report(rows, as_json=False, verbose=False):
    if as_json:
        print(json.dumps([dict(zip(("level", "check", "detail"), r)) for r in rows], indent=1))
    else:
        for level, check, detail in rows:
            if verbose or level != "ok":
                print(f"{level.upper():5} {check} {detail}")
    fails = sum(r[0] == "fail" for r in rows)
    warns = sum(r[0] == "warn" for r in rows)
    summary = f"tv: {len(rows)} checks, {warns} warn, {fails} fail"
    if not as_json:
        print(summary)
    return summary, fails


def notify(summary, rows):
    lines = [f"{c} {d}" for lvl, c, d in rows if lvl != "ok"]
    if lines and subprocess.run(["sh", "-c", "command -v notify-send"], capture_output=True).returncode == 0:
        subprocess.run(["notify-send", "-a", "tv", summary, "\n".join(lines[:6])])


def main(argv):
    flags = {a for a in argv if a.startswith("-")}
    args = [a for a in argv if not a.startswith("-")]
    cmd = args.pop(0) if args else "status"
    conf = load_conf()
    STATE.mkdir(parents=True, exist_ok=True)
    stamp = STATE / "last-update"
    weekly = "--weekly" in flags
    if weekly and stamp.exists() and time.time() - stamp.stat().st_mtime < float(conf["WEEKLY_DAYS"]) * 86400 - 3600:
        return 0

    tv = connect(conf)
    if tv is None:
        if weekly:  # TV off or in deep standby: the daily timer retries tomorrow; nag only when long overdue
            overdue = not stamp.exists() or time.time() - stamp.stat().st_mtime > 2 * float(conf["WEEKLY_DAYS"]) * 86400
            if overdue and "--notify" in flags:
                notify("tv: unreachable over adb", [("warn", "adb", "turn the TV on; updates are overdue")])
            return 0
        sys.exit(f"tv: no adb connection to {conf['TV_ADB'] or 'the TV'} (TV on? Network debugging on? Accept the prompt on the TV)")
    if cmd == "connect":
        print(f"tv: connected to {tv.serial}")
        return 0

    names = args or conf["APPS"].split()
    out = []
    if cmd in ("status", "update"):
        rows = plan(tv, names)
        busy = tv.foreground() if weekly else None
        for r in rows:
            check, have = f"app:{r['app']}", r["installed"] or "-"
            if r["state"] == "unknown":
                out.append(("warn", check, f"{have}; latest unknown: {r['detail']}"))
            elif r["state"] == "current":
                out.append(("ok", check, have))
            elif cmd == "status" or "--dry-run" in flags:
                out.append(("warn", check, f"{r['state']}: {have} -> {r['latest'] or 'install'}"))
            elif r["pkg"] == busy:
                out.append(("warn", check, f"{have} -> {r['latest']} deferred: in use on the TV"))
            else:
                try:
                    install(tv, r)
                    out.append(("ok", check, f"{have} -> {tv.version(r['pkg'])}"))
                    print(f"tv: {r['app']} {have} -> {tv.version(r['pkg'])}")
                except Exception as e:
                    out.append(("fail", check, f"{have} -> {r['latest']}: {e}"))
        if cmd == "update" and not any(lvl != "ok" for lvl, _, _ in out) and "--dry-run" not in flags:
            stamp.touch()
    if cmd in ("status", "setup"):
        out += list(setup_checks(tv, conf, apply=cmd == "setup"))
    elif cmd != "update":
        sys.exit(__doc__)

    summary, fails = report(out, "--json" in flags, "-v" in flags)
    (STATE / "last.txt").write_text("\n".join("\t".join(r) for r in out) + "\n" + summary + "\n")
    if "--notify" in flags:
        notify(summary, out)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
