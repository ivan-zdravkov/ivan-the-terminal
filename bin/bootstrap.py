#!/usr/bin/env python3
"""Set up (or repair) this machine for ivan-the-terminal. Idempotent; safe to re-run. Stdlib only.
  Linux:   brew toolchain, symlinks, ~/.bashrc.d hook, systemd --user units
  Windows: winget toolchain, junctions + itt.cmd shim, PowerShell profile hook (services: docs/roadmap.md)
  --no-extras   skip the per-skill tools (tier "extra" in toolchain.txt)
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ITT_HOME = Path(os.environ.get("ITT_HOME") or Path(__file__).resolve().parents[1])
PRIVATE_DIR = Path(os.environ.get("ITT_PRIVATE_DIR") or ITT_HOME.parent / "ivan-the-terrible")
CFG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
HOME = Path.home()
WINDOWS = os.name == "nt"
sys.path.insert(0, str(ITT_HOME / "tools"))
import toolchain  # noqa: E402


def say(msg):
    print(f"==> {msg}", flush=True)


def is_link(p):
    return p.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(p))


def link(target, path):
    """Point PATH at TARGET; back up a real file/dir once. Windows directories get a junction (no admin needed)."""
    target, path = Path(target), Path(path)
    if is_link(path):
        if os.path.realpath(path) == os.path.realpath(target):
            return
        os.rmdir(path) if WINDOWS and path.is_dir() else path.unlink()
    elif path.exists():
        backup = path.with_name(f"{path.name}.pre-itt.{time.strftime('%Y%m%d%H%M%S')}")
        path.rename(backup)
        say(f"backed up existing {path} to {backup.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if WINDOWS and target.is_dir():
        subprocess.run(["cmd", "/c", "mklink", "/J", str(path), str(target)], check=True, capture_output=True)
    else:
        os.symlink(target, path, target_is_directory=target.is_dir())


# ---- Windows ----------------------------------------------------------------------------------

def user_path():
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
        try:
            return winreg.QueryValueEx(k, "Path")[0]
        except FileNotFoundError:
            return ""


def add_to_path(directory):
    """Append DIRECTORY to the user PATH (registry) and to this process; tell running shells it changed."""
    import ctypes
    import winreg
    directory = os.path.expandvars(directory)
    current = user_path()
    if directory.lower() not in [p.lower().rstrip("\\") for p in current.split(";") if p]:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "Path", 0, winreg.REG_EXPAND_SZ, f"{current.rstrip(';')};{directory}".lstrip(";"))
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "Environment", 2, 5000, None)  # WM_SETTINGCHANGE
        say(f"added {directory} to PATH")
    refresh_path()


def refresh_path():
    """Re-read PATH from the registry so tools installed a moment ago are found."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment") as k:
        machine = winreg.QueryValueEx(k, "Path")[0]
    os.environ["PATH"] = os.path.expandvars(f"{machine};{user_path()}")


def winget_install(row):
    cmd = ["winget", "install", "--id", row["winget"], "-e", "--silent", "--accept-package-agreements",
           "--accept-source-agreements", "--disable-interactivity"]
    if row["win_dir"]:
        cmd += ["--location", os.path.expandvars(row["win_dir"])]
    return subprocess.run(cmd).returncode == 0


def powershell_profiles():
    """Profile paths of PowerShell 7 and Windows PowerShell 5.1 (Documents may be redirected)."""
    for exe in ("pwsh", "powershell"):
        if shutil.which(exe):
            out = subprocess.run([exe, "-NoProfile", "-Command", "$PROFILE.CurrentUserCurrentHost"],
                                 capture_output=True, text=True).stdout.strip()
            if out:
                yield exe, Path(out)


def claude_home_windows():
    line = f'. "{ITT_HOME / "shell" / "claude-home.ps1"}"  # ivan-the-terminal: interactive claude starts here'
    for exe, profile in powershell_profiles():
        text = profile.read_text(encoding="utf-8-sig") if profile.exists() else ""
        if "claude-home.ps1" not in text:
            profile.parent.mkdir(parents=True, exist_ok=True)
            profile.write_text(text + ("\n" if text and not text.endswith("\n") else "") + line + "\n", encoding="utf-8")
            say(f"{exe}: {profile} loads claude-home.ps1")
    # Windows PowerShell 5.1 defaults to Restricted, which would skip the profile
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "if ((Get-ExecutionPolicy) -in 'Restricted','AllSigned','Undefined') "
                    "{ Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force }"], capture_output=True)


# ---- steps ------------------------------------------------------------------------------------

def install_toolchain(extras):
    say("toolchain")
    if WINDOWS and not shutil.which("winget"):
        sys.exit("winget is required (App Installer from the Microsoft Store)")
    if not WINDOWS and not shutil.which("brew"):
        sys.exit("Homebrew is required: https://brew.sh (preinstalled on Bazzite)")
    missing = []
    for row in toolchain.read():
        if row["tier"] != "core" and not extras:
            continue
        if WINDOWS and row["win_dir"] and Path(os.path.expandvars(row["win_dir"])).is_dir():
            add_to_path(row["win_dir"])  # installed, maybe not on PATH yet
        if not shutil.which(row["cmd"]) and toolchain.package(row, WINDOWS):
            missing.append(row)
    if not missing:
        return
    if WINDOWS:
        for row in missing:
            say(f"winget install {row['winget']} ({row['cmd']})")
            if winget_install(row) and row["win_dir"]:
                add_to_path(row["win_dir"])
        refresh_path()
    else:
        subprocess.run(["brew", "install", *[r["brew"] for r in missing]], check=True)


def install_itt():
    if WINDOWS:
        say("itt on PATH (~/.local/bin/itt.cmd)")
        shim = HOME / ".local" / "bin" / "itt.cmd"
        shim.parent.mkdir(parents=True, exist_ok=True)
        shim.write_text(f'@python3 -I "{ITT_HOME / "bin" / "itt"}" %*\r\n', encoding="utf-8")
        add_to_path(str(shim.parent))
    else:
        say("itt on PATH (~/.local/bin)")
        link(ITT_HOME / "bin" / "itt", HOME / ".local/bin/itt")


def claude_home():
    say("shell: interactive claude starts in ivan-the-terminal")
    if WINDOWS:
        claude_home_windows()
        return
    link(ITT_HOME / "shell/claude-home.bash", HOME / ".bashrc.d/claude-home.sh")
    bashrc = HOME / ".bashrc"
    if "bashrc.d" not in (bashrc.read_text(encoding="utf-8") if bashrc.exists() else ""):
        say('WARNING: ~/.bashrc doesn\'t source ~/.bashrc.d; add: for rc in ~/.bashrc.d/*; do . "$rc"; done')


def link_skills():
    say("skills -> ~/.claude/skills")
    for skill in sorted(ITT_HOME.glob("plugins/*/skills/*/SKILL.md")):
        link(skill.parent, HOME / ".claude/skills" / skill.parent.name)


def services():
    if WINDOWS:
        say("plugin timers and services: not on Windows yet (Task Scheduler port, docs/roadmap.md)")
        return
    say("plugin timers and services (systemd --user)")
    units = sorted(ITT_HOME.glob("plugins/*/systemd/*.service")) + sorted(ITT_HOME.glob("plugins/*/systemd/*.timer"))
    for unit in units:
        if os.path.realpath(CFG / "systemd/user" / unit.name) != str(unit):
            subprocess.run(["systemctl", "--user", "link", str(unit)], capture_output=True)
    subprocess.run(["systemctl", "--user", "daemon-reload"])
    # Timers, and long-running services that declare [Install]; oneshot services are started by their timers.
    for unit in units:
        if unit.suffix == ".timer" or "\n[Install]" in "\n" + unit.read_text(encoding="utf-8"):
            subprocess.run(["systemctl", "--user", "enable", "--now", unit.name], capture_output=True)


def private_overlay():
    say("private overlay")
    if not (PRIVATE_DIR / ".git").is_dir():
        user = subprocess.run(["gh", "api", "user", "-q", ".login"], capture_output=True, text=True).stdout.strip()
        repo = os.environ.get("ITT_PRIVATE_REPO") or f"{user or 'unknown'}/ivan-the-terrible"
        if subprocess.run(["gh", "repo", "clone", repo, str(PRIVATE_DIR)], capture_output=True).returncode:
            say(f"no private overlay ({repo} not reachable): generic mode")
    script = PRIVATE_DIR / "bin" / "bootstrap"
    if script.is_file():
        with open(script, "rb") as f:
            python = b"python" in f.readline()
        subprocess.run([sys.executable, "-I", str(script)] if python else [str(script)], check=True)
    denylist = CFG / "ivan-the-terminal" / "leakguard.denylist"
    if denylist.is_file() and denylist.stat().st_size:
        subprocess.run(["git", "-C", str(ITT_HOME), "config", "leakguard.requireDenylist", "true"], check=True)


def main(args):
    install_toolchain(extras="--no-extras" not in args)
    say("git hooks")
    subprocess.run(["git", "-C", str(ITT_HOME), "config", "core.hooksPath", ".githooks"], check=True)
    install_itt()
    claude_home()
    link_skills()
    services()
    private_overlay()
    say("done. Next: itt doctor" + (" (open a new terminal first: PATH changed)" if WINDOWS else ""))


if __name__ == "__main__":
    main(sys.argv[1:])
