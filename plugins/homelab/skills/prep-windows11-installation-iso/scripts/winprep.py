#!/usr/bin/env python3
"""Prepare a debloated, unattended Windows 11 install USB.

  run.py plan                        config, apps and removals that would go on the stick
  run.py iso                         newest Windows 11 ISO in ISO_DIR + SHA-256, or how to download one
  run.py answer                      build autounattend.xml (WIN11_PASSWORD / WIN11_PRODUCT_KEY from the env)
  run.py apps [app...]               download + verify installers, write install-apps.ps1 and restore-keys.ps1
  run.py usb --device /dev/sdX --format --yes   Linux: format the stick, write ISO + answer file + payload
  run.py usb [--payload-only]        Linux: (re)write onto the stick labelled USB_LABEL
  run.py tune                        Windows: apply the desktop + gaming tune-up to this PC (UAC prompt)

Config: ~/.config/ivan-the-terminal/prep-windows11-installation-iso.conf (template: config.example).
Build dir: ~/.local/state/ivan-the-terminal/prep-windows11-installation-iso/ (answer file, payload, downloads).
The password and product key are only substituted locally; the generator site never sees them.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
import posixpath
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from xml.dom import minidom

SKILL = "prep-windows11-installation-iso"
CONF = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "ivan-the-terminal" / f"{SKILL}.conf"
STATE = Path.home() / ".local" / "state" / "ivan-the-terminal" / SKILL
UA = "ivan-the-terminal/prep-windows11-installation-iso (+https://github.com/ivan-zdravkov/ivan-the-terminal)"
TUNE = Path(__file__).resolve().parent / "tune-windows.ps1"
GENERATOR = "https://schneegans.de/windows/unattend-generator/download/"
WINGET = "microsoft/winget-pkgs"
PW_PLACEHOLDER = "XPLACEHOLDERX"
BS = "\\"  # a Windows path separator inside f-strings
# Microsoft's published generic install keys: they pick the edition but never activate.
GENERIC_KEYS = {"pro": "VK7JG-NPHTM-C97JM-9MPGT-3V66T", "home": "YTMG3-N6DKC-DKB77-7M9GH-8HVX7"}
DOWNLOAD_PAGE = "https://www.microsoft.com/software-download/windows11"

DEFAULTS = {
    "ACCOUNT": "Admin",
    "COMPUTER_NAME": "",
    "LANGUAGE": "en-US",
    "INPUT": "en-US:00000409",
    "GEO_LOCATION": "244",
    "TIMEZONE": "",
    "EDITION": "pro",
    "APPS": "brave claude claude-code steam battlenet ea epic ubisoft gog vscode git",
    "REMOVE": ("3DViewer BingSearch Camera Clipchamp Clock Copilot Cortana DevHome WindowsHello Family FeedbackHub "
               "GameAssist GetHelp Handwriting InternetExplorer MailCalendar Maps MathInputPanel MixedReality ZuneVideo "
               "News Office365 OneDrive OneNote OneSync Outlook Paint3D People PowerAutomate PowerShell2 PowerShellISE "
               "QuickAssist Recall RdpClient Skype Solitaire Speech StepsRecorder StickyNotes Teams GetStarted ToDo "
               "VoiceRecorder Wallet Weather WindowsMediaPlayer ZuneMusic WordPad XboxApps YourPhone"),
    "KEYS_VOLUME": "",
    "KEYS_DIR": "",
    "GIT_NAME": "",
    "GIT_EMAIL": "",
    "ISO_DIR": "~/Downloads",
    "USB_LABEL": "WIN11",
    "GENERATOR_EXTRA": "",
    # tune-windows.ps1, run after the apps at first logon (and by `tune` on a live PC)
    "TASKBAR": "center autohide alltray",
    "TASKBAR_PINS": "",
    "AUTOSTART_OFF": "Steam Battle.net EADM EADesktop GalaxyClient GogGalaxy EpicGamesLauncher Ubisoft* Uplay*",
    "DEBLOAT": "Edge FaxScan CrossDevice",
    "STORE_APPS": "",
    "POWER": "",
    "APOLLO": "",
}

# The debloat profile: every option of the generator we set (see references/answer-file.md).
BASE_SETTINGS = {
    "LanguageMode": "Unattended", "PEMode": "Default", "ProcessorArchitecture": "amd64",
    "WindowsEditionMode": "Custom", "PartitionMode": "Interactive", "PagingFileMode": "Automatic",
    "BypassNetworkCheck": "true", "UserAccountMode": "Unattended", "AutoLogonMode": "Own",
    "ObscurePasswords": "true", "PasswordExpirationMode": "Unlimited", "LockoutMode": "Default",
    "HideFiles": "Hidden", "ShowFileExtensions": "true", "ShowEndTask": "true", "TaskbarSearch": "Hide",
    "TaskbarIconsMode": "Empty", "DisableWidgets": "true", "HideTaskViewButton": "true",
    "DisableBingResults": "true", "StartTilesMode": "Default", "StartPinsMode": "Empty",
    "DisableFastStartup": "true", "EnableLongPaths": "true", "DisableAppSuggestions": "true",
    "PreventDeviceEncryption": "true", "HideEdgeFre": "true", "DisableEdgeStartupBoost": "true",
    "MakeEdgeUninstallable": "true", "DeleteEdgeDesktopIcon": "true", "DisablePointerPrecision": "true",
    "DisableWpbt": "true", "PreventDeviceApps": "true", "EffectsMode": "Default", "DesktopIconsMode": "Default",
    "StartFoldersMode": "Default", "CoreIsolationMode": "Enabled", "WifiMode": "Skip",
    "ExpressSettings": "DisableAll", "LockKeysMode": "Skip", "StickyKeysMode": "Disabled", "ColorMode": "Default",
    "WallpaperMode": "Default", "LockScreenMode": "Default", "AppLockerMode": "Skip",
}

# App catalog. winget apps take URL, SHA-256 and silent switches from the winget-pkgs manifest.
# `signer` must appear in the Authenticode subject: checked here when a fixed URL drifted past the manifest
# hash, and always on Windows right before the installer runs.
CATALOG = {
    "brave": {"source": "github", "repo": "brave/brave-browser", "asset": "BraveBrowserStandaloneSilentSetup.exe",
              "type": "exe", "args": "", "signer": "Brave Software", "label": "Brave"},
    "claude": {"source": "claude-desktop", "type": "msix", "label": "Claude desktop"},
    "claude-code": {"source": "claude-code", "type": "claude-code", "signer": "Anthropic", "label": "Claude Code"},
    "steam": {"source": "winget", "id": "Valve.Steam", "signer": "Valve", "label": "Steam"},
    "battlenet": {"source": "winget", "id": "Blizzard.BattleNet", "signer": "Blizzard", "label": "Battle.net"},
    "ea": {"source": "winget", "id": "ElectronicArts.EADesktop", "signer": "Electronic Arts", "label": "EA app"},
    "epic": {"source": "winget", "id": "EpicGames.EpicGamesLauncher", "signer": "Epic Games", "label": "Epic Games Launcher"},
    "ubisoft": {"source": "winget", "id": "Ubisoft.Connect", "signer": "Ubisoft", "label": "Ubisoft Connect"},
    "gog": {"source": "winget", "id": "GOG.Galaxy", "signer": "GOG", "label": "GOG Galaxy"},
    "vscode": {"source": "winget", "id": "Microsoft.VisualStudioCode", "signer": "Microsoft Corporation", "label": "Visual Studio Code"},
    "git": {"source": "winget", "id": "Git.Git", "signer": None, "label": "Git for Windows"},  # versioned URL: hash only
    "7zip": {"source": "winget", "id": "7zip.7zip", "signer": None, "label": "7-Zip"},  # unsigned: hash only
    "qbittorrent": {"source": "winget", "id": "qBittorrent.qBittorrent", "signer": None, "label": "qBittorrent"},  # unsigned
    "stremio": {"source": "winget", "id": "Stremio.Stremio", "signer": "Smart Code", "label": "Stremio"},
    "potplayer": {"source": "winget", "id": "Daum.PotPlayer", "signer": "Kakao Corp", "label": "PotPlayer"},  # fixed URL
    "tailscale": {"source": "winget", "id": "Tailscale.Tailscale", "signer": "Tailscale Inc", "label": "Tailscale"},
    # Moonlight host (Sunshine fork) with its own virtual display driver; unsigned: hash only
    "apollo": {"source": "winget", "id": "ClassicOldSong.Apollo", "signer": None, "label": "Apollo"},
}
# APPS="runtimes": what PC games expect to find (Visual C++ 2005-2022, legacy DirectX 9-11 DLLs, XNA, .NET).
# .NET Framework 3.5 is a Windows feature: tune-windows.ps1 enables it.
RUNTIMES = [f"Microsoft.VCRedist.{v}.{a}" for v in ("2005", "2008", "2010", "2012", "2013", "2015+") for a in ("x86", "x64")]
RUNTIMES += ["Microsoft.DirectX", "Microsoft.XNARedist", "Microsoft.DotNet.DesktopRuntime.8", "Microsoft.DotNet.DesktopRuntime.10"]
# winget packages that need more than their installer: a preferred installer type, a step after installing.
WINGET_EXTRAS = {
    "Microsoft.PowerShell": {"prefer": "wix"},  # the machine-wide MSI, not the msixbundle
    "Microsoft.DirectX": {"prefer": "exe"},  # dxwebsetup (the June 2010 DLLs), not the UWP framework appx
    "Python.PythonInstallManager": {  # the manager alone has no Python: add the default runtime + its PATH entry
        "post": "& (Join-Path $env:LOCALAPPDATA 'Microsoft\\WindowsApps\\py.exe') install --configure -y"},
}
SILENT_DEFAULTS = {"inno": "/SP- /VERYSILENT /SUPPRESSMSGBOXES /NORESTART", "nullsoft": "/S",
                   "burn": "/quiet /norestart", "msi": "/quiet /norestart", "wix": "/quiet /norestart"}


def die(msg):
    sys.exit(f"{SKILL}: {msg}")


def say(msg):
    print(msg, flush=True)


# ---- config ---------------------------------------------------------------------------------

def parse_conf(text):
    conf = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        words = shlex.split(value, comments=True)
        conf[key.strip()] = " ".join(words)
    return conf


def load_conf(path=CONF):
    conf = dict(DEFAULTS)
    if path.exists():
        conf.update(parse_conf(path.read_text(encoding="utf-8")))
    else:
        say(f"note: no {path}; using defaults (template: config.example)")
    return conf


def toolchain_rows():
    """toolchain.txt rows Windows gets from winget (APPS="toolchain"): ivan-the-terminal's tools, core and extra."""
    module = Path(__file__).resolve().parents[5] / "tools" / "toolchain.py"
    if not module.is_file():
        die("APPS has 'toolchain', which needs an ivan-the-terminal checkout (tools/toolchain.py)")
    spec = importlib.util.spec_from_file_location("toolchain", module)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return [r for r in mod.read() if r["winget"]]


def app_names(conf):
    names = []
    for n in conf["APPS"].split():
        if n == "toolchain":
            names += [f"toolchain:{r['cmd']}" for r in toolchain_rows()]
        elif n == "runtimes":
            names += [f"winget:{pid}" for pid in RUNTIMES]
        elif n in CATALOG or n.startswith("winget:"):
            names.append(n)
        else:
            die(f"unknown app '{n}' in APPS (known: {' '.join(CATALOG)}, toolchain, runtimes, or winget:<Package.Id>)")
    seen, unique = set(), []  # one install per package: e.g. "git" and the toolchain's Git.Git
    for n in names:
        key = app_spec(n).get("id") or n
        if key not in seen:
            seen.add(key)
            unique.append(n)
    return unique


def app_spec(name):
    if name.startswith("winget:"):
        pid = name.split(":", 1)[1]
        return {"source": "winget", "id": pid, "signer": None, "label": pid, **WINGET_EXTRAS.get(pid, {})}
    if name.startswith("toolchain:"):
        cmd = name.split(":", 1)[1]
        row = next((r for r in toolchain_rows() if r["cmd"] == cmd), None) or die(f"no '{cmd}' in toolchain.txt")
        return {"source": "winget", "id": row["winget"], "signer": None, "label": f"{cmd} ({row['winget']})",
                "cmd": cmd, "win_dir": row["win_dir"], **WINGET_EXTRAS.get(row["winget"], {})}
    return CATALOG[name]


# ---- http -----------------------------------------------------------------------------------

def github_token():
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not tok and shutil.which("gh"):
        p = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, encoding="utf-8")
        tok = p.stdout.strip() if p.returncode == 0 else None
    return tok


def http(url, data=None, headers=None, as_json=False):
    h = {"User-Agent": UA, **(headers or {})}
    if url.startswith("https://api.github.com/") and github_token():
        h["Authorization"] = f"Bearer {github_token()}"
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=60) as r:
        body = r.read()
    return json.loads(body) if as_json else body


def download(url, dest):
    """Stream URL to dest; return (sha256, final URL)."""
    h = hashlib.sha256()
    tmp = dest.with_name(dest.name + ".part")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120) as r, \
            open(tmp, "wb") as f:
        final = r.geturl()
        for chunk in iter(lambda: r.read(1 << 20), b""):
            h.update(chunk)
            f.write(chunk)
    os.replace(tmp, dest)
    return h.hexdigest(), final


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---- winget manifests (a YAML subset: maps, lists, scalars) ---------------------------------

def yaml_load(text):
    lines = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or stripped == "---":
            continue
        content = re.sub(r"\s+#.*$", "", raw.rstrip()) if not re.search(r"['\"]", raw) else raw.rstrip()
        lines.append([len(raw) - len(raw.lstrip(" ")), content.strip()])
    value, _ = _yaml_block(lines, 0, lines[0][0] if lines else 0)
    return value


def _scalar(s):
    if len(s) >= 2 and s[0] == s[-1] == "'":
        return s[1:-1].replace("''", "'")
    if len(s) >= 2 and s[0] == s[-1] == '"':
        return s[1:-1].encode("utf-8").decode("unicode_escape")
    return s


def _is_key(s):
    return re.match(r"^[A-Za-z0-9_.-]+:(\s|$)", s) is not None


def _yaml_block(lines, i, indent):
    if i < len(lines) and lines[i][1].startswith("- "):
        out = []
        while i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("- "):
            item = lines[i][1][2:].strip()
            if _is_key(item):
                lines[i] = [indent + 2, item]
                value, i = _yaml_block(lines, i, indent + 2)
            else:
                value, i = _scalar(item), i + 1
            out.append(value)
        return out, i
    out = {}
    while i < len(lines) and lines[i][0] == indent and not lines[i][1].startswith("- "):
        key, _, rest = lines[i][1].partition(":")
        rest = rest.strip()
        i += 1
        if rest:
            out[key] = _scalar(rest)
        elif i < len(lines) and (lines[i][0] > indent or (lines[i][0] == indent and lines[i][1].startswith("- "))):
            out[key], i = _yaml_block(lines, i, lines[i][0])
        else:
            out[key] = None
    return out, i


def vkey(v):
    return tuple(int(x) for x in re.findall(r"\d+", v))


def winget_manifest(pid):
    parts = pid.split(".")
    base = f"manifests/{parts[0][0].lower()}/{'/'.join(parts)}"
    listing = http(f"https://api.github.com/repos/{WINGET}/contents/{base}", as_json=True)
    versions = [e["name"] for e in listing if e["type"] == "dir" and re.match(r"\d", e["name"])]
    if not versions:
        raise LookupError(f"no versions for {pid} in winget-pkgs")
    version = max(versions, key=vkey)
    text = http(f"https://raw.githubusercontent.com/{WINGET}/master/{base}/{version}/{pid}.installer.yaml")
    return version, yaml_load(text.decode("utf-8"))


def pick_installer(manifest, arch="x64", prefer=None):
    """PREFER's installer type when offered, then machine scope and our arch, then neutral/x86; top-level fields
    are the defaults."""
    shared = {k: v for k, v in manifest.items() if k != "Installers"}
    cands = []
    for inst in manifest.get("Installers") or []:
        merged = {**shared, **inst}
        merged["InstallerSwitches"] = {**(shared.get("InstallerSwitches") or {}), **(inst.get("InstallerSwitches") or {})}
        cands.append(merged)
    if not cands:
        raise LookupError("manifest has no installers")
    rank_arch = {arch: 0, "neutral": 1, "x86": 2}
    cands = [c for c in cands if c.get("Architecture") in rank_arch]
    if not cands:
        raise LookupError(f"no {arch}/neutral/x86 installer")
    if prefer and any((c.get("InstallerType") or "").lower() == prefer for c in cands):
        cands = [c for c in cands if (c.get("InstallerType") or "").lower() == prefer]
    return min(cands, key=lambda c: (rank_arch[c.get("Architecture")], 0 if c.get("Scope", "machine") == "machine" else 1))


def silent_args(inst, location=None):
    """(type, switches); LOCATION fills <INSTALLPATH> when the installer needs one and the manifest has no default."""
    kind = (inst.get("InstallerType") or "exe").lower()
    sw = inst.get("InstallerSwitches") or {}
    args = sw.get("Silent") or SILENT_DEFAULTS.get(kind, "")
    for word in (sw.get("Custom") or "").split():
        if word not in args.split():
            args = f"{args} {word}".strip()
    if inst.get("InstallLocationRequired") in (True, "true") and sw.get("InstallLocation"):
        loc = (inst.get("InstallationMetadata") or {}).get("DefaultInstallLocation") or location
        if loc:
            args = f"{args} {sw['InstallLocation'].replace('<INSTALLPATH>', loc)}".strip()
    return kind, args


# ---- signatures -----------------------------------------------------------------------------

def ca_bundle():
    for p in ("/etc/pki/tls/certs/ca-bundle.crt", "/etc/ssl/certs/ca-certificates.crt", "/etc/ssl/cert.pem"):
        if Path(p).exists():
            return p
    return None


def authenticode(path):
    """('ok'|'untrusted'|'invalid'|'unchecked', subject). 'untrusted' = intact, but the root CA isn't in the
    local bundle (e.g. Microsoft Trusted Signing); Windows still checks it before running. Needs osslsigncode."""
    tool, bundle = shutil.which("osslsigncode"), ca_bundle()
    if not tool or not bundle:
        return "unchecked", None
    p = subprocess.run([tool, "verify", "-CAfile", bundle, "-TSA-CAfile", bundle, "-in", str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"Signer's certificate:(?:\n[^\n]*){0,3}?\n\s*Subject:\s*([^\n]+)", p.stdout)
    subject = m.group(1).strip() if m else None
    cur = re.search(r"Current message digest\s*:\s*(\w+)", p.stdout)
    calc = re.search(r"Calculated message digest\s*:\s*(\w+)", p.stdout)
    if not subject or not cur or not calc or cur.group(1) != calc.group(1):
        return "invalid", subject
    if p.returncode == 0 and "Signature verification: ok" in p.stdout:
        return "ok", subject
    return "untrusted", subject


def msix_publisher(path):
    with zipfile.ZipFile(path) as z:
        if "AppxSignature.p7x" not in z.namelist():
            return None
        m = re.search(r'<Identity[^>]*Publisher="([^"]+)"', z.read("AppxManifest.xml").decode("utf-8", "replace"))
    return m.group(1).replace("&quot;", '"') if m else None


# ---- apps -----------------------------------------------------------------------------------

def resolve(name):
    """-> dict(version, url, sha256 or None, file, type, args, signer)."""
    spec = app_spec(name)
    src = spec["source"]
    if src == "winget":
        version, man = winget_manifest(spec["id"])
        inst = pick_installer(man, prefer=spec.get("prefer"))
        kind, args = silent_args(inst, spec.get("win_dir"))
        if kind == "zip" and (inst.get("NestedInstallerType") or "").lower() != "portable":
            raise LookupError("only zips of portable programs are supported")
        url = inst["InstallerUrl"]
        ext = {"msi": ".msi", "wix": ".msi", "msix": ".msix", "zip": ".zip"}.get(kind, ".exe")
        nested = [f["RelativeFilePath"] for f in inst.get("NestedInstallerFiles") or []]
        alias = spec.get("cmd") or ((inst.get("Commands") or []) + [spec["id"].split(".")[-1].lower()])[0]
        return {"version": version, "url": url, "sha256": inst["InstallerSha256"].lower(), "type": kind,
                "args": args, "signer": spec.get("signer"), "file": f"{name.replace(':', '-')}-{version}{ext}",
                "nested": nested, "alias": alias, "win_dir": spec.get("win_dir"), "post": spec.get("post")}
    if src == "github":
        rel = http(f"https://api.github.com/repos/{spec['repo']}/releases/latest", as_json=True)
        asset = next(a for a in rel["assets"] if a["name"] == spec["asset"])
        digest = (asset.get("digest") or "").removeprefix("sha256:") or None
        return {"version": rel["tag_name"].lstrip("v"), "url": asset["browser_download_url"], "sha256": digest,
                "type": spec["type"], "args": spec["args"], "signer": spec.get("signer"), "file": f"{name}-{spec['asset']}"}
    if src == "claude-code":
        base = "https://downloads.claude.ai/claude-code-releases"
        version = http(f"{base}/latest").decode("utf-8").strip()
        if not re.fullmatch(r"\d+\.\d+\.\d+\S*", version):
            raise LookupError("unexpected Claude Code version response")
        man = http(f"{base}/{version}/manifest.json", as_json=True)
        return {"version": version, "url": f"{base}/{version}/win32-x64/claude.exe",
                "sha256": man["platforms"]["win32-x64"]["checksum"].lower(), "type": "claude-code", "args": "",
                "signer": spec["signer"], "file": "claude.exe"}
    if src == "claude-desktop":
        return {"version": "latest", "url": "https://claude.ai/api/desktop/win32/x64/msix/latest/redirect",
                "sha256": None, "type": "msix", "args": "", "signer": "Anthropic, PBC", "file": "Claude.msix"}
    raise LookupError(f"unknown source {src}")


def fetch(name, info, cache):
    """Download into cache and verify. Returns (path, how-verified)."""
    dest = cache / info["file"]
    if dest.exists() and info["sha256"] and sha256(dest) == info["sha256"]:
        return dest, "sha256 (cached)"
    digest, _ = download(info["url"], dest)
    if info["sha256"] and digest == info["sha256"]:
        return dest, "sha256"
    if info["type"] == "msix":
        pub = msix_publisher(dest)
        if pub and info["signer"] and info["signer"] in pub:
            return dest, f"signed MSIX ({info['signer']})"
    elif info["signer"]:
        status, subject = authenticode(dest)
        named = subject and info["signer"].lower() in subject.lower().replace("\\,", ",")
        if status == "ok" and named:
            return dest, f"Authenticode ({info['signer']}); manifest hash outdated"
        if status in ("untrusted", "unchecked") and (named or status == "unchecked"):
            return dest, f"hash drifted, signature {status} here; Windows checks it is {info['signer']}'s before running"
    dest.unlink()
    raise ValueError(f"verification failed (got sha256 {digest})")


def ps_quote(s):
    return "'" + s.replace("'", "''") + "'"


def tune_call(conf, script, log=None):
    """PowerShell call of tune-windows.ps1 (SCRIPT: a PowerShell path expression) with the conf's settings."""
    args = [("Taskbar", "TASKBAR"), ("Pins", "TASKBAR_PINS"), ("AutostartOff", "AUTOSTART_OFF"),
            ("Debloat", "DEBLOAT"), ("StoreApps", "STORE_APPS"), ("Power", "POWER"), ("Apollo", "APOLLO")]
    call = f"& {script}" + "".join(f" -{p} {ps_quote(conf[k])}" for p, k in args)
    return call + (f" -Log {ps_quote(log)}" if log else "")


def install_script(items, tune=None):
    """PowerShell run at first logon from C:\\Setup\\Installers (items: [(name, info)]; TUNE: a tune_call)."""
    out = ["# Generated by ivan-the-terminal prep-windows11-installation-iso. Re-run by hand if anything failed.",
           "$dir = $PSScriptRoot",
           "Start-Transcript -Path (Join-Path $dir 'install-apps.log') -Append | Out-Null",
           "$report = @()",
           "$tools = Join-Path $env:LOCALAPPDATA 'Programs\\ivan-the-terminal'  # zip and portable tools",
           "function AddPath($d) {",
           "  $d = [Environment]::ExpandEnvironmentVariables($d)",
           "  $p = [Environment]::GetEnvironmentVariable('Path', 'User')",
           "  if (($p -split ';') -notcontains $d) { [Environment]::SetEnvironmentVariable('Path', ($p.TrimEnd(';') + ';' + $d).TrimStart(';'), 'User') }",
           "}",
           "function Hashed($file, $sha) { return (Get-FileHash -Algorithm SHA256 (Join-Path $dir $file)).Hash -eq $sha }",
           "function Signed($file, $signer) {",
           "  $s = Get-AuthenticodeSignature -FilePath (Join-Path $dir $file)",
           "  return $s.Status -eq 'Valid' -and (-not $signer -or $s.SignerCertificate.Subject -like \"*$signer*\")",
           "}",
           "function Run($label, $exe, $arguments) {",
           "  Write-Host \"Installing ${label}...\"",
           "  $p = if ($arguments) { Start-Process -FilePath $exe -ArgumentList $arguments -PassThru }",
           "       else { Start-Process -FilePath $exe -PassThru }",
           "  # WaitForExit, not -Wait: launchers start their client as a child that never exits",
           "  if (-not $p.WaitForExit(1800000)) { return \"${label}: still running after 30 min\" }",
           "  return \"${label}: exit code $($p.ExitCode)\"",
           "}"]
    for name, info in items:
        text = app_spec(name)["label"]
        label, f = ps_quote(text), ps_quote(info["file"])
        path = f"(Join-Path $dir {f})"
        kind = info["type"]
        if kind in ("zip", "portable") or (kind != "msix" and info.get("sha256") and not info.get("signer")):
            # no publisher to check (often unsigned, e.g. 7-Zip): the winget SHA-256 is checked again on the target
            sha = ps_quote(info["sha256"].upper())
            out.append(f"if (-not (Hashed {f} {sha})) {{ $report += {ps_quote(text + ': SKIPPED, hash mismatch')} }} else {{")
        elif kind != "msix":  # Add-AppxPackage verifies MSIX signatures itself
            signer = ps_quote(info.get("signer") or "")
            out.append(f"if (-not (Signed {f} {signer})) {{ $report += {ps_quote(text + ': SKIPPED, signature not valid')} }} else {{")
        if kind == "zip":
            dest = f"(Join-Path $tools {ps_quote(name.replace(':', '-'))})"
            out.append(f"Expand-Archive -Path {path} -DestinationPath {dest} -Force")
            for d in sorted({posixpath.dirname(n) for n in info.get("nested") or []}):
                out.append(f"AddPath {dest}" if not d else f"AddPath (Join-Path {dest} {ps_quote(d.replace('/', BS))})")
            out.append(f"$report += {ps_quote(text + ': installed')}")
        elif kind == "portable":
            exe = ps_quote(f"bin{BS}{info['alias']}.exe")
            out.append("New-Item -ItemType Directory -Force (Join-Path $tools 'bin') | Out-Null")
            out.append(f"Copy-Item {path} (Join-Path $tools {exe}) -Force; AddPath (Join-Path $tools 'bin')")
            out.append(f"$report += {ps_quote(text + ': installed')}")
        elif kind in ("msi", "wix"):
            args = ps_quote(f'/i "{{0}}" {info["args"]}'.strip())
            out.append(f"$report += Run {label} 'msiexec.exe' ({args} -f {path})")
        elif kind == "msix":
            out.append(f"try {{ Add-AppxPackage -Path {path} -ErrorAction Stop; $report += {ps_quote(text + ': installed')} }}"
                       f" catch {{ $report += {ps_quote(text + ': FAILED ')} + $_ }}")
        elif kind == "claude-code":
            out.append(f"& {path} install; $report += {ps_quote(text + ': exit code ')} + $LASTEXITCODE")
        else:
            args = ps_quote(info["args"]) if info["args"] else "$null"
            if "%" in info["args"]:  # e.g. %PROGRAMFILES(X86)% in an install path; Start-Process won't expand it
                args = f"([Environment]::ExpandEnvironmentVariables({args}))"
            out.append(f"$report += Run {label} {path} {args}")
        if info.get("win_dir"):
            out.append(f"AddPath {ps_quote(info['win_dir'])}")
        if info.get("post"):
            out.append(f"{info['post']}; $report += {ps_quote(text + ': setup exit code ')} + $LASTEXITCODE")
        if kind != "msix":
            out.append("}")
    if tune:  # after every app, so their shortcuts and Run entries exist
        out.append(f"{tune} | ForEach-Object {{ $report += \"tune: $_\" }}")
    out += ["$keys = Join-Path $dir 'restore-keys.ps1'",
            "if (Test-Path $keys) { & $keys; $report += \"keys and git: exit code $LASTEXITCODE\" }",
            "$report | Tee-Object -FilePath (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Setup report.txt')",
            "Stop-Transcript | Out-Null"]
    return "\n".join(out) + "\n"


GITHUB_HOST_KEY = "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"


def keys_script(conf):
    vol, sub = conf["KEYS_VOLUME"], conf["KEYS_DIR"]
    lines = ["# Restore SSH + age keys from a drive and configure Git for Windows. Safe to re-run.",
             "$ErrorActionPreference = 'Continue'"]
    if vol:
        lines += [
            f"$label = {ps_quote(vol)}; $sub = {ps_quote(sub)}",
            "$v = Get-Volume | Where-Object { $_.FileSystemLabel -eq $label -and $_.DriveLetter } | Select-Object -First 1",
            "if (-not $v) { Write-Warning \"Drive '$label' not found. Plug it in, then run: powershell -ExecutionPolicy Bypass -File $PSCommandPath\"; exit 1 }",
            "$src = Join-Path \"$($v.DriveLetter):\\\" $sub",
            "$ssh = Join-Path $HOME '.ssh'; New-Item -ItemType Directory -Force $ssh | Out-Null",
            "if (Test-Path (Join-Path $src 'ssh')) { Copy-Item (Join-Path $src 'ssh\\*') $ssh -Force }",
            "Get-ChildItem $ssh -File | Where-Object { $_.Extension -ne '.pub' -and $_.Name -notlike 'known_hosts*' -and $_.Name -ne 'config' } |",
            "  ForEach-Object { icacls $_.FullName /inheritance:r /grant:r \"$($env:USERNAME):F\" | Out-Null }",
            f"$kh = Join-Path $ssh 'known_hosts'; $gh = {ps_quote(GITHUB_HOST_KEY)}",
            "if (-not ((Test-Path $kh) -and (Select-String -Path $kh -SimpleMatch $gh -Quiet))) { Add-Content -Path $kh -Value $gh }",
            "$ageSrc = Join-Path $src 'age\\keys.txt'",
            "if (Test-Path $ageSrc) {",
            "  $age = Join-Path $env:APPDATA 'sops\\age'; New-Item -ItemType Directory -Force $age | Out-Null",
            "  Copy-Item $ageSrc (Join-Path $age 'keys.txt') -Force",
            "  icacls (Join-Path $age 'keys.txt') /inheritance:r /grant:r \"$($env:USERNAME):F\" | Out-Null",
            "}",
            "# Windows OpenSSH agent: the key passphrase is asked once per login",
            "Set-Service ssh-agent -StartupType Automatic; Start-Service ssh-agent",
        ]
    lines += ["$git = Join-Path $env:ProgramFiles 'Git\\cmd\\git.exe'",
              "if (Test-Path $git) {",
              "  & $git config --global core.sshCommand 'C:/Windows/System32/OpenSSH/ssh.exe'"]
    if conf["GIT_NAME"]:
        lines.append(f"  & $git config --global user.name {ps_quote(conf['GIT_NAME'])}")
    if conf["GIT_EMAIL"]:
        lines.append(f"  & $git config --global user.email {ps_quote(conf['GIT_EMAIL'])}")
    lines += ["}", "Write-Host 'Keys and Git configured.'", "exit 0"]
    return "\n".join(lines) + "\n"


# ---- answer file ----------------------------------------------------------------------------

def obscure(password):
    """How Windows Setup stores an obscured <Password> value."""
    return base64.b64encode((password + "Password").encode("utf-16-le")).decode()


def generator_params(conf):
    edition = conf["EDITION"].lower()
    if edition not in GENERIC_KEYS:
        die(f"EDITION must be one of {', '.join(GENERIC_KEYS)}")
    p = dict(BASE_SETTINGS)
    pairs = [x.split(":") for x in conf["INPUT"].split()]
    if not pairs or len(pairs) > 3 or any(len(x) != 2 for x in pairs):
        die("INPUT must be 1-3 locale:keyboard pairs, e.g. 'en-US:00000409 bg-BG:00040402'")
    p.update({"UILanguage": conf["LANGUAGE"], "Locale": pairs[0][0], "Keyboard": pairs[0][1],
              "GeoLocation": conf["GEO_LOCATION"], "ProductKey": GENERIC_KEYS[edition],
              "AccountName0": conf["ACCOUNT"], "AccountDisplayName0": conf["ACCOUNT"],
              "AccountPassword0": PW_PLACEHOLDER, "AccountGroup0": "Administrators"})
    for n, (loc, kb) in enumerate(pairs[1:], start=2):
        p.update({f"UseKeyboard{n}": "true", f"Locale{n}": loc, f"Keyboard{n}": kb})
    if conf["COMPUTER_NAME"]:
        p.update({"ComputerNameMode": "Custom", "ComputerName": conf["COMPUTER_NAME"]})
    if conf["TIMEZONE"]:
        p.update({"TimeZoneMode": "Explicit", "TimeZone": conf["TIMEZONE"]})
    for r in conf["REMOVE"].split():
        p[f"Remove{r}"] = "true"
    for kv in shlex.split(conf["GENERATOR_EXTRA"]):
        k, _, v = kv.partition("=")
        p[k] = v
    return p


FIRST_LOGON = ("powershell.exe -WindowStyle \"Normal\" -ExecutionPolicy \"Unrestricted\" -NoProfile -Command \""
               "$d='C:\\Setup\\Installers'; $f=Join-Path $d 'install-apps.ps1'; if (-not (Test-Path $f)) { "
               "$src = Get-PSDrive -PSProvider FileSystem | ForEach-Object { Join-Path $_.Root '$OEM$\\$1\\Setup\\Installers' } | "
               "Where-Object { Test-Path (Join-Path $_ 'install-apps.ps1') } | Select-Object -First 1; "
               "if ($src) { New-Item -ItemType Directory -Force $d | Out-Null; Copy-Item (Join-Path $src '*') $d -Force } }; "
               "&amp; $f\"")


def finalize_answer(xml, password, product_key, generic_key, with_apps=True):
    """Substitute secrets locally, hide online-account screens, add the first-logon app install."""
    xml = xml.replace("\r\n", "\n")
    old = obscure(PW_PLACEHOLDER)
    if xml.count(old) != 2:
        raise ValueError(f"expected 2 password placeholders, found {xml.count(old)}")
    xml = xml.replace(old, obscure(password)).replace(PW_PLACEHOLDER, "")
    if product_key:
        if not re.fullmatch(r"[A-Z0-9]{5}(-[A-Z0-9]{5}){4}", product_key):
            raise ValueError("product key must look like XXXXX-XXXXX-XXXXX-XXXXX-XXXXX")
        for tag in ("Key", "ProductKey"):
            xml = xml.replace(f"<{tag}>{generic_key}</{tag}>", f"<{tag}>{product_key}</{tag}>")
    xml = xml.replace("<HideOnlineAccountScreens>false</HideOnlineAccountScreens>",
                      "<HideOnlineAccountScreens>true</HideOnlineAccountScreens>")
    if with_apps:
        block = re.search(r"<FirstLogonCommands>(.*?)</FirstLogonCommands>", xml, re.S)
        if not block:
            raise ValueError("no FirstLogonCommands in the generated file")
        order = max([int(o) for o in re.findall(r"<Order>(\d+)</Order>", block.group(1))] or [0]) + 1
        cmd = (f"\t<SynchronousCommand wcm:action=\"add\">\n\t\t\t\t\t<Order>{order}</Order>\n"
               f"\t\t\t\t\t<CommandLine>{FIRST_LOGON}</CommandLine>\n"
               f"\t\t\t\t\t<Description>Install apps and restore keys</Description>\n\t\t\t\t</SynchronousCommand>\n\t\t\t")
        xml = xml[:block.end(1)] + cmd + xml[block.end(1):]
    return xml


def build_answer(conf, out):
    params = generator_params(conf)
    query = urllib.parse.urlencode(params)
    xml = http(f"{GENERATOR}?{query}").decode("utf-8")
    pw = os.environ.get("WIN11_PASSWORD")
    if pw is None:
        die("set WIN11_PASSWORD (empty string = no password), e.g. via sops exec-env; never pass it as an argument")
    key = os.environ.get("WIN11_PRODUCT_KEY", "").strip().upper() or None
    xml = finalize_answer(xml, pw, key, GENERIC_KEYS[conf["EDITION"].lower()], with_apps=bool(conf["APPS"].split()))
    minidom.parseString(xml.encode("utf-8"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(xml, encoding="utf-8", newline="\n")
    return key is not None


# ---- ISO ------------------------------------------------------------------------------------

def find_iso(conf):
    d = Path(os.path.expanduser(conf["ISO_DIR"]))
    isos = [p for p in d.glob("*.iso") if re.search(r"win(dows)?[ _-]?11", p.name, re.I)]
    partial = list(d.glob("*.crdownload")) + list(d.glob("*.part"))
    return (max(isos, key=lambda p: p.stat().st_mtime) if isos else None), partial


# ---- USB (Linux: udisks + wimlib, no sudo) --------------------------------------------------

def run(cmd, **kw):
    return subprocess.run(cmd, check=True, text=True, encoding="utf-8", capture_output=True, **kw).stdout


def lsblk(dev=None):
    out = run(["lsblk", "-J", "-b", "-o", "NAME,PATH,SIZE,RM,TRAN,TYPE,LABEL,MODEL,MOUNTPOINTS"] + ([dev] if dev else []))
    return json.loads(out)["blockdevices"]


def udisks(path, method, *args):
    obj = "/org/freedesktop/UDisks2/block_devices/" + Path(path).name
    return run(["gdbus", "call", "--system", "--dest", "org.freedesktop.UDisks2", "--object-path", obj,
                "--method", f"org.freedesktop.UDisks2.{method}", *args])


def mount(dev):
    for d in lsblk(dev):
        if any(d.get("mountpoints") or []):
            return Path([m for m in d["mountpoints"] if m][0])
    out = run(["udisksctl", "mount", "-b", dev])
    return Path(out.strip().split(" at ", 1)[1].rstrip("."))


def format_stick(device, label):
    disk = lsblk(device)[0]
    if disk.get("type") != "disk" or not disk.get("rm") or disk.get("tran") != "usb":
        die(f"{device} is not a removable USB disk ({disk.get('model')}); refusing to format")
    for part in disk.get("children") or []:
        if any(part.get("mountpoints") or []):
            run(["udisksctl", "unmount", "-b", part["path"]])
    udisks(device, "Block.Format", "gpt", "{}")
    udisks(device, "PartitionTable.CreatePartitionAndFormat", "1048576", "0",
           "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7", label, "{}", "vfat", f"{{'label': <'{label}'>}}")
    time.sleep(2)


def stick_partition(label):
    for disk in lsblk():
        for part in disk.get("children") or []:
            if part.get("label") == label and disk.get("rm") and disk.get("tran") == "usb":
                return part["path"]
    return None


def copy_tree(src, dst, skip=()):
    for f in sorted(src.rglob("*")):
        rel = f.relative_to(src)
        if rel.as_posix() in skip:
            continue
        t = dst / rel
        if f.is_dir():
            t.mkdir(parents=True, exist_ok=True)
        else:
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, t)


def write_payload(dst, build):
    shutil.copyfile(build / "autounattend.xml", dst / "autounattend.xml")
    oem = dst / "$OEM$" / "$1" / "Setup" / "Installers"
    if oem.exists():
        shutil.rmtree(oem)
    oem.mkdir(parents=True)
    if (build / "payload").is_dir():
        copy_tree(build / "payload", oem)


def write_stick(iso, part, build):
    loop = run(["udisksctl", "loop-setup", "-r", "-f", str(iso)])
    loop = re.search(r"/dev/loop\d+", loop).group(0)
    try:
        time.sleep(2)
        src, dst = mount(loop), mount(part)
        wim = src / "sources" / "install.wim"
        need = sum(f.stat().st_size for f in src.rglob("*") if f.is_file())
        need += sum(f.stat().st_size for f in (build / "payload").rglob("*") if f.is_file())
        if need > shutil.disk_usage(dst).total:
            die(f"stick too small: need {need / 2**30:.1f} GiB")
        for child in dst.iterdir():
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        say("copying setup files...")
        copy_tree(src, dst, skip={"sources/install.wim"})
        if wim.exists():
            say("splitting install.wim for FAT32 (slow on USB 2 sticks)...")
            subprocess.run(["wimlib-imagex", "split", str(wim), str(dst / "sources" / "install.swm"), "3800"], check=True)
        write_payload(dst, build)
        subprocess.run(["sync"], check=True)
        missing = [f.relative_to(src).as_posix() for f in src.rglob("*") if f.is_file()
                   and f != wim and not (dst / f.relative_to(src)).exists()]
        if missing:
            die(f"{len(missing)} files missing on the stick, e.g. {missing[0]}")
        if wim.exists():
            subprocess.run(["wimlib-imagex", "verify", str(dst / "sources" / "install.swm"),
                            f"--ref={dst / 'sources' / 'install*.swm'}"], check=True, capture_output=True)
        say("verified: every ISO file present, split image intact")
    finally:
        subprocess.run(["udisksctl", "unmount", "-b", loop], capture_output=True)
        subprocess.run(["udisksctl", "loop-delete", "-b", loop], capture_output=True)


# ---- commands -------------------------------------------------------------------------------

def cmd_plan(conf, a):
    say(f"account {conf['ACCOUNT']} (local admin), computer {conf['COMPUTER_NAME'] or '(random)'}, "
        f"edition {conf['EDITION']}, language {conf['LANGUAGE']}, input {conf['INPUT']}, "
        f"geo {conf['GEO_LOCATION']}, timezone {conf['TIMEZONE'] or '(automatic)'}")
    say(f"apps at first logon: {', '.join(app_spec(n)['label'] for n in app_names(conf)) or 'none'}")
    say(f"removed: {conf['REMOVE']}; after the apps: {conf['DEBLOAT'] or 'nothing'}")
    say(f"taskbar: {conf['TASKBAR'] or 'unchanged'}; pins: {conf['TASKBAR_PINS'] or 'unchanged'}; "
        f"autostart off: {conf['AUTOSTART_OFF'] or '-'}; Store apps: {conf['STORE_APPS'] or '-'}")
    say(f"power: {conf['POWER'] or 'Windows defaults'}; Apollo: {conf['APOLLO'] or 'defaults'}")
    say(f"keys: {conf['KEYS_VOLUME'] + ':' + chr(92) + conf['KEYS_DIR'] if conf['KEYS_VOLUME'] else 'not restored'}"
        f"; git identity: {conf['GIT_NAME'] or '-'} <{conf['GIT_EMAIL'] or '-'}>")
    say(f"secrets in env: WIN11_PASSWORD {'set' if 'WIN11_PASSWORD' in os.environ else 'MISSING'}, "
        f"WIN11_PRODUCT_KEY {'set' if os.environ.get('WIN11_PRODUCT_KEY') else 'not set (generic key: no activation)'}")


def cmd_iso(conf, a):
    iso, partial = find_iso(conf)
    if partial:
        say(f"download in progress: {partial[0].name} ({partial[0].stat().st_size / 2**30:.1f} GiB so far)")
    if not iso:
        say(f"no Windows 11 ISO in {conf['ISO_DIR']}. Microsoft gates the download behind its web page:\n"
            f"  1. open {DOWNLOAD_PAGE}\n"
            "  2. 'Download Windows 11 Disk Image (ISO) for x64 devices' -> Windows 11 (multi-edition ISO) -> Download Now\n"
            "  3. pick the language -> Confirm -> 64-bit Download, save it to ISO_DIR")
        return 1
    cache = STATE / "iso.sha256"
    stamp = f"{iso.name}\t{iso.stat().st_size}\t{int(iso.stat().st_mtime)}"
    known = cache.read_text(encoding="utf-8").split("\n") if cache.exists() else []
    if len(known) >= 2 and known[0] == stamp:
        digest = known[1]
    else:
        digest = sha256(iso)
        STATE.mkdir(parents=True, exist_ok=True)
        cache.write_text(f"{stamp}\n{digest}\n", encoding="utf-8")
    say(f"{iso}  {iso.stat().st_size / 2**30:.2f} GiB\nsha256 {digest}\n"
        f"compare with the hash list on {DOWNLOAD_PAGE} (shown after choosing the language)")
    return 0


def cmd_answer(conf, a):
    out = STATE / "autounattend.xml"
    keyed = build_answer(conf, out)
    say(f"wrote {out} ({'product key in file' if keyed else 'generic key: activate later'}; password obscured)")
    say("it holds the password: delete it from the stick after installing")
    return 0


def cmd_apps(conf, a):
    names = a.names or app_names(conf)
    cache, payload = STATE / "downloads", STATE / "payload"
    cache.mkdir(parents=True, exist_ok=True)
    items, failed = [], []
    for name in names:
        try:
            info = resolve(name)
            path, how = fetch(name, info, cache)
            items.append((name, info))
            say(f"ok    {app_spec(name)['label']} {info['version']}  ({how})")
        except Exception as e:  # report every app, then fail
            failed.append(name)
            say(f"FAIL  {name}: {e}")
    if failed:
        die(f"{len(failed)} app(s) failed: {' '.join(failed)}; drop them from APPS or retry")
    if payload.exists():
        shutil.rmtree(payload)
    payload.mkdir(parents=True)
    for _, info in items:
        shutil.copyfile(cache / info["file"], payload / info["file"])
    shutil.copyfile(TUNE, payload / TUNE.name)
    tune = tune_call(conf, f"(Join-Path $dir {ps_quote(TUNE.name)})")
    (payload / "install-apps.ps1").write_text(install_script(items, tune), encoding="utf-8-sig", newline="\r\n")
    (payload / "restore-keys.ps1").write_text(keys_script(conf), encoding="utf-8-sig", newline="\r\n")
    (payload / "apps.json").write_text(json.dumps({n: i for n, i in items}, indent=1), encoding="utf-8")
    size = sum(f.stat().st_size for f in payload.iterdir()) / 2**20
    say(f"payload: {len(items)} installers, {size:.0f} MiB in {payload}")
    return 0


def cmd_usb(conf, a):
    if sys.platform != "linux":
        die("writing the stick is Linux-only for now; on Windows use Rufus with the ISO, then copy "
            f"{STATE / 'autounattend.xml'} and {STATE / 'payload'} (as $OEM$\\$1\\Setup\\Installers) to its root")
    for tool in ("udisksctl", "gdbus", "lsblk") + (() if a.payload_only else ("wimlib-imagex",)):
        if not shutil.which(tool):
            die(f"{tool} not found" + (" (brew install wimlib)" if tool == "wimlib-imagex" else ""))
    build = STATE
    if not (build / "autounattend.xml").exists():
        die("no answer file yet: run `answer` first")
    label = conf["USB_LABEL"]
    if a.format:
        if not a.device or not a.yes:
            die("--format needs --device /dev/sdX and --yes (it erases the whole stick)")
        format_stick(a.device, label)
    part = stick_partition(label)
    if not part:
        die(f"no USB partition labelled {label}; format one with --device /dev/sdX --format --yes")
    if a.payload_only:
        dst = mount(part)
        write_payload(dst, build)
        subprocess.run(["sync"], check=True)
    else:
        iso, _ = find_iso(conf)
        if not iso:
            die("no ISO: run `iso` first")
        write_stick(iso, part, build)
    subprocess.run(["udisksctl", "unmount", "-b", part], capture_output=True)
    say(f"stick ready on {part} ({label}); boot it from the firmware's one-time boot menu (UEFI entry)")
    return 0


def cmd_tune(conf, a):
    if sys.platform != "win32":
        die("tune changes this Windows PC; run it on Windows")
    log = Path(tempfile.gettempdir()) / "ivan-the-terminal-tune.log"
    log.unlink(missing_ok=True)
    inner = tune_call(conf, ps_quote(str(TUNE)), str(log))
    encoded = base64.b64encode(inner.encode("utf-16-le")).decode()  # no quoting through Start-Process
    outer = ("$p = Start-Process powershell.exe -Verb RunAs -Wait -PassThru -WindowStyle Hidden -ArgumentList "
             f"'-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand','{encoded}'; exit $p.ExitCode")
    p = subprocess.run(["powershell.exe", "-NoProfile", "-Command", outer])
    if log.exists():  # the elevated window's output, minus the transcript header and footer
        parts = re.split(r"\*{10,}", log.read_text(encoding="utf-8", errors="replace"))
        say((parts[2] if len(parts) > 2 else parts[0]).strip())
    return p.returncode


def main(argv=None):
    ap = argparse.ArgumentParser(description="Prepare a debloated, unattended Windows 11 install USB.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan")
    sub.add_parser("iso")
    sub.add_parser("answer")
    p = sub.add_parser("apps")
    p.add_argument("names", nargs="*")
    p = sub.add_parser("usb")
    p.add_argument("--device")
    p.add_argument("--format", action="store_true")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--payload-only", action="store_true")
    sub.add_parser("tune")
    a = ap.parse_args(argv)
    conf = load_conf()
    return {"plan": cmd_plan, "iso": cmd_iso, "answer": cmd_answer, "apps": cmd_apps, "usb": cmd_usb, "tune": cmd_tune}[a.cmd](conf, a) or 0


if __name__ == "__main__":
    sys.exit(main())
