#!/usr/bin/env python3
"""daily-coach: build today's plan headless (claude -p) from Health data + replies, and email it.
  run.py                 import new Health sync files, make today's plan and email it (re-plans if one exists:
                         check-ins on matching item ids are kept)
  run.py --if-ready      what the schedule runs every 15 min from AUTO_PLAN_HOUR: import, then make the plan once
                         last night's sleep has arrived (20+ min after waking), or at PLAN_BY at the latest
  run.py --import        only import new Health sync files and print what arrived
  run.py --dry-run       assemble prompt + command and print a summary; runs nothing
  run.py --install-task  Windows: register that schedule in Task Scheduler (Linux: daily-coach.timer)
Private config: ~/.config/ivan-the-terminal/daily-coach/{config.env,profile.md} (see ../config.example)
Stdlib only; Linux and Windows. On Windows the run's Bash tool is Git Bash, which Claude Code needs anyway.
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
DEFAULTS = {"MODEL": "claude-sonnet-5-5", "MAIL_TO": "", "WEB_DOMAINS": "", "AUTO_PLAN_HOUR": "6",
            "PLAN_BY": "10:30"}
G = "mcp__claude_ai_Gmail"
# The Windows task starts pythonw (no console window), which has no stdio: hooks and children need python.exe
PY = Path(sys.executable).with_name("python.exe") if Path(sys.executable).name.lower() == "pythonw.exe" \
    else Path(sys.executable)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def load_envfile():
    spec = importlib.util.spec_from_file_location("envfile", SKILL.parents[3] / "tools/envfile.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def coach(*args, **kw):
    return subprocess.run([str(PY), "-I", "-X", "utf8", str(TOOLS / "coach.py"), *args], creationflags=NO_WINDOW,
                          **kw)


def rule_path(path):
    """Permission-rule form of an absolute path: "//" + the POSIX path, with a Windows drive as /c/..."""
    p = Path(path).as_posix()
    drive, sep, rest = p.partition(":/")
    return f"//{drive.lower()}/{rest}" if sep and len(drive) == 1 else f"/{p}"


def prompt_for(work):
    text = (SKILL / "references/prompt.md").read_text(encoding="utf-8")
    profile = (CONF / "profile.md").read_text(encoding="utf-8").strip()
    for key, value in (("{{PROFILE}}", profile), ("{{WORK}}", work.as_posix()), ("{{TOOLS}}", TOOLS.as_posix())):
        text = text.replace(key, value)
    return text


def settings_for(work, to, domains):
    guard = shlex.join([str(PY), "-I", TOOLS.joinpath("guard.py").as_posix(), TOOLS.as_posix(), work.as_posix(), to,
                        *domains])  # hooks run in bash, also on Windows (Git Bash)
    return {"hooks": {"PreToolUse": [{"matcher": "Bash|PowerShell|Monitor|Write|Edit|WebFetch|mcp__.*",
                                      "hooks": [{"type": "command", "command": guard}]}]}}


def command(model, settings, work):
    """Least privilege: no interpreter, Read/Write only inside WORK, Gmail read plus one send to MAIL_TO (the guard
    checks it). Recipe pages and mail are untrusted, so nothing here may turn an injection into code, mail or a leak."""
    work_rule, tools = f"{rule_path(work)}/**", TOOLS.as_posix()
    allowed = [*(f"Bash({tools}/coach.py {c}:*)" for c in ("context", "checks-set", "plan-set", "email", "has-plan",
                                                             "status")),
               "Bash(date:*)", f"Read({work_rule})", f"Edit({work_rule})", "WebSearch", "WebFetch",
               f"{G}__search_threads", f"{G}__get_thread", f"{G}__send_message"]
    disallowed = [f"{G}__{t}" for t in ("get_message", "create_draft", "update_draft", "delete_draft", "reply", "forward",
                                        "label_thread", "label_message", "unlabel_thread", "unlabel_message",
                                        "trash_message", "trash_thread", "mark_message_spam", "mark_thread_spam")]
    return ["claude", "-p", "--model", model, "--permission-mode", "dontAsk", "--settings", str(settings),
            "--allowedTools", *allowed, "--disallowedTools", *disallowed, "PowerShell", "Monitor", "Agent", "Task",
            "NotebookEdit"], allowed


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


def past(hhmm, now=None):
    h, m = (int(x) for x in hhmm.split(":"))
    now = now or datetime.now()
    return (now.hour, now.minute) >= (h, m)


def install_task(start_hour, plan_by):
    if os.name != "nt":
        sys.exit("daily-coach: --install-task is for Windows; Linux uses plugins/health/systemd/daily-coach.timer")
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    h, m = (int(x) for x in plan_by.split(":"))
    minutes = max(15, (h * 60 + m) - int(start_hour) * 60 + 15)  # keep polling until just after PLAN_BY
    q = lambda s: "'" + str(s).replace("'", "''") + "'"
    ps = (f"$a = New-ScheduledTaskAction -Execute {q(pyw if pyw.exists() else exe)} "
          f"-Argument {q(chr(34) + str(Path(__file__).resolve()) + chr(34) + ' --if-ready')} -WorkingDirectory {q(HOME)}; "
          f"$t = New-ScheduledTaskTrigger -Daily -At {q(f'{int(start_hour):02d}:00')}; "
          f"$t.Repetition = (New-ScheduledTaskTrigger -Once -At {q(f'{int(start_hour):02d}:00')} "
          f"-RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Minutes {minutes})).Repetition; "
          "$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
          "-RunOnlyIfNetworkAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30); "
          "Register-ScheduledTask -TaskName daily-coach -Action $a -Trigger $t -Settings $s -Force | Out-Null")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    print(f"daily-coach: scheduled every 15 min from {int(start_hour):02d}:00; the plan is made once last night's sleep "
          f"has arrived, by {plan_by} at the latest (Task Scheduler: daily-coach)")
    return 0


def desktop_notify(title, body):
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", title, body])


def main(argv):
    if sys.stdout:  # None under pythonw (the Windows task)
        sys.stdout.reconfigure(encoding="utf-8")
    mode = argv[0] if argv else ""
    if not (CONF / "config.env").is_file() or not (CONF / "profile.md").is_file():
        print(f"daily-coach: not configured: create {CONF}/config.env and profile.md "
              f"(templates in {SKILL}/config.example)")
        return 0
    cfg = load_envfile().env(CONF / "config.env", DEFAULTS)
    model, to, domains = cfg["MODEL"], cfg["MAIL_TO"].strip(), cfg["WEB_DOMAINS"].lower().split()
    if not to or not domains:  # the run reads mail: WebFetch must stay on the recipe sites
        print(f"daily-coach: set MAIL_TO and WEB_DOMAINS in {CONF}/config.env", file=sys.stderr)
        return 2
    if mode == "--install-task":
        return install_task(cfg["AUTO_PLAN_HOUR"], cfg["PLAN_BY"])

    for d in (STATE / "work", STATE / "logs"):
        d.mkdir(parents=True, exist_ok=True)
    work, logs = (STATE / "work").resolve(), STATE / "logs"  # resolved: permission rules see real paths
    if mode == "--dry-run":
        prompt = prompt_for(work)
        unfilled = sum("{{" in line for line in prompt.splitlines())
        print(f"prompt: {len(prompt.encode())} bytes, {unfilled} unfilled placeholders")
        print(f"model: {model}  mail to: {to}  work: {work}  schedule: every 15 min from "
              f"{int(cfg['AUTO_PLAN_HOUR']):02d}:00, plan by {cfg['PLAN_BY']}")
        print(f"guard: {settings_for(work, to, domains)['hooks']['PreToolUse'][0]['hooks'][0]['command']}")
        print("status:")
        status = coach("status", capture_output=True, text=True, encoding="utf-8")
        print("".join(f"  {line}\n" for line in (status.stdout + status.stderr).splitlines()), end="")
        return 0

    held = lock(STATE / "lock")
    if not held:
        print("daily-coach: a run is already in progress")
        return 0
    log = logs / f"{datetime.now():%Y-%m-%d_%H%M}.log"
    imported = coach("import", capture_output=True, text=True, encoding="utf-8")
    if mode == "--import":
        print((imported.stdout + imported.stderr).strip())
        return imported.returncode
    if mode == "--if-ready":
        if coach("has-plan").returncode == 0:
            return 0
        if coach("ready").returncode != 0 and not past(cfg["PLAN_BY"]):
            return 0  # no sleep data yet: the next poll checks again

    for p in work.iterdir():
        shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()
    settings = STATE / "settings.json"
    settings.write_text(json.dumps(settings_for(work, to, domains), indent=2), encoding="utf-8")
    cmd, _ = command(model, settings, work)
    with open(log, "w", encoding="utf-8") as out:
        print(f"import: {(imported.stdout + imported.stderr).strip()}", file=out, flush=True)
        try:  # prompt on stdin: not visible in /proc/*/cmdline
            status = subprocess.run(cmd, input=prompt_for(work), text=True, encoding="utf-8", stdout=out,
                                    stderr=subprocess.STDOUT, cwd=work, creationflags=NO_WINDOW,
                                    env={**os.environ, "DAILY_COACH_WORK": str(work)}).returncode
        except FileNotFoundError as e:
            print(f"daily-coach: {e}", file=out)
            status = 127
    if status == 0 and coach("has-plan").returncode != 0:
        status = 3  # finished without storing a plan
    if status != 0:
        desktop_notify("Daily coach failed", f"See {log}")
    cutoff = time.time() - 30 * 86400
    for old in logs.glob("*.log"):
        if old.stat().st_mtime < cutoff:
            old.unlink()
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
