#!/usr/bin/env python3
"""daily-coach: build today's plan headless (claude -p) from ring data + check-ins, store it for the Daily app, push.
  run.py               make today's plan (re-plans if one exists: check-ins on matching item ids are kept)
  run.py --if-missing  only if today has no plan yet (what the wake trigger and the fallback timer use)
  run.py --dry-run     assemble prompt + command and print a summary; runs nothing
  run.py --serve       run the check-in/ingest server (what daily-coach-server.service does)
Private config: ~/.config/ivan-the-terminal/daily-coach/{config.env,profile.md} (see ../config.example)
Stdlib only. --serve and --dry-run work everywhere; the real run is POSIX-only until the PowerShell-tool allowlist.
"""
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
TOOLS = SKILL / "scripts"
HOME = Path.home()
CONF = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / "ivan-the-terminal/daily-coach"
STATE = Path(os.environ.get("XDG_STATE_HOME") or HOME / ".local/state") / "ivan-the-terminal/daily-coach"
DATA = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local/share") / "ivan-the-terminal/daily-coach"


def load_webapp():
    spec = importlib.util.spec_from_file_location("webapp", SKILL.parents[3] / "tools/webapp/webapp.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def tool(name, *args):
    return [sys.executable, "-I", "-X", "utf8", str(TOOLS / name), *args]  # UTF-8 pipes on Windows too


def prompt_for(work):
    text = (SKILL / "references/prompt.md").read_text(encoding="utf-8")
    profile = (CONF / "profile.md").read_text(encoding="utf-8").strip()
    for key, value in (("{{PROFILE}}", profile), ("{{WORK}}", str(work)), ("{{TOOLS}}", str(TOOLS))):
        text = text.replace(key, value)
    return text


def settings_for(work, domains):
    guard = shlex.join([sys.executable, "-I", str(TOOLS / "guard.py"), str(TOOLS), str(work), *domains])
    return {"hooks": {"PreToolUse": [{"matcher": "Bash|Write|Edit|WebFetch|mcp__.*",
                                      "hooks": [{"type": "command", "command": guard}]}]}}


def command(model, settings, work):
    """Least privilege: no interpreter, Read/Write only inside WORK, no mail or other MCP tools (the plan goes to the
    app). Recipe pages are untrusted, so nothing here may turn an injection into code, mail or a leak."""
    work_rule = f"/{work}/**"  # "//abs/path" = absolute path; Edit(...) rules also cover Write (Write(...) rules are ignored)
    allowed = [f"Bash({TOOLS}/coach.py context:*)", f"Bash({TOOLS}/coach.py plan-set:*)",
               f"Bash({TOOLS}/coach.py has-plan:*)", f"Bash({TOOLS}/coach.py status:*)", "Bash(date:*)",
               f"Read({work_rule})", f"Edit({work_rule})", "WebSearch", "WebFetch"]
    return ["claude", "-p", "--model", model, "--permission-mode", "dontAsk", "--settings", str(settings),
            "--allowedTools", *allowed, "--disallowedTools", "mcp__claude_ai_Gmail", "NotebookEdit"], allowed


def lock(path):
    """Exclusive non-blocking lock held for the life of the process; None when another run holds it."""
    f = open(path, "a+")
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def clear(directory):
    for p in directory.iterdir():
        shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()


def desktop_notify(title, body):
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", title, body])


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")  # same as the helpers (-X utf8), whatever the Windows code page
    mode = argv[0] if argv else ""
    if not (CONF / "config.env").is_file() or not (CONF / "profile.md").is_file():
        print(f"daily-coach: not configured: create {CONF}/config.env and profile.md "
              f"(templates in {SKILL}/config.example)")
        return 0
    cfg = load_webapp().env(CONF / "config.env", {"MODEL": "claude-sonnet-5-5", "WEB_DOMAINS": ""})
    model, domains = cfg["MODEL"], cfg["WEB_DOMAINS"].split()

    if mode == "--serve":
        if os.name == "posix":
            os.execv(sys.executable, tool("coach.py", "serve"))  # same PID for systemd
        return subprocess.run(tool("coach.py", "serve")).returncode
    if mode == "--if-missing" and subprocess.run(tool("coach.py", "has-plan")).returncode == 0:
        return 0

    for d in (STATE / "work", STATE / "logs", DATA):
        d.mkdir(parents=True, exist_ok=True)
    held = lock(STATE / "lock")
    if not held:
        print("daily-coach: a run is already in progress")
        return 0
    work, logs = (STATE / "work").resolve(), STATE / "logs"  # resolved: permission rules see real paths
    clear(work)
    prompt = prompt_for(work)
    settings = STATE / "settings.json"
    settings.write_text(json.dumps(settings_for(work, domains), indent=2), encoding="utf-8")
    cmd, _ = command(model, settings, work)

    if mode == "--dry-run":
        unfilled = sum("{{" in line for line in prompt.splitlines())
        print(f"prompt: {len(prompt.encode())} bytes, {unfilled} unfilled placeholders")
        print(f"model: {model}  work: {work}")
        print(f"guard: {settings_for(work, domains)['hooks']['PreToolUse'][0]['hooks'][0]['command']}")
        print("status:")
        status = subprocess.run(tool("coach.py", "status"), capture_output=True, text=True, encoding="utf-8")
        print("".join(f"  {line}\n" for line in status.stdout.splitlines()), end="")
        sys.stdout.flush()  # the child writes straight to the fd: keep our lines first
        subprocess.run(tool("coach.py", "url"))
        return 0
    if os.name != "posix":
        print("daily-coach: the headless run is POSIX-only for now (Windows needs the PowerShell-tool allowlist)")
        return 2

    log = logs / f"{datetime.now():%Y-%m-%d_%H%M}.log"
    with open(log, "w", encoding="utf-8") as out:
        try:  # prompt on stdin: not visible in /proc/*/cmdline
            status = subprocess.run(cmd, input=prompt, text=True, encoding="utf-8", stdout=out, stderr=subprocess.STDOUT,
                                    cwd=work, env={**os.environ, "DAILY_COACH_WORK": str(work)}).returncode
        except FileNotFoundError as e:
            print(f"daily-coach: {e}", file=out)
            status = 127
    (DATA / "last-trigger").unlink(missing_ok=True)  # let the phone trigger again if this run failed
    if status == 0 and subprocess.run(tool("coach.py", "has-plan")).returncode != 0:
        status = 3  # finished without storing a plan
    if status == 0:  # best effort: the app shows it either way
        with open(log, "a", encoding="utf-8") as out:
            subprocess.run(tool("coach.py", "notify"), stdout=out, stderr=subprocess.STDOUT)
    if status != 0:
        desktop_notify("Daily coach failed", f"See {log}")
    cutoff = time.time() - 30 * 86400
    for old in logs.glob("*.log"):
        if old.stat().st_mtime < cutoff:
            old.unlink()
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
