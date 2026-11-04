#!/usr/bin/env python3
"""game-graphics: tune PC games' graphics settings; `daily` runs the unattended pass headless (claude -p).
  run.py <graphics.py subcommand> ...   scan, peek, apply, diff, restore, backups, optiscaler, system (see graphics.py)
  run.py daily                          what the task runs: new/changed games researched, tuned, reported by email
  run.py daily --dry-run                assemble prompt + command and print a summary; runs nothing
  run.py --install-task                 Windows: schedule `daily` at RUN_AT via Task Scheduler
Private config: ~/.config/ivan-the-terminal/game-graphics/{config.env,profile.md} (see ../config.example)
Stdlib only. On Windows the run's Bash tool is Git Bash, which Claude Code needs anyway.
"""
import json
import os
import re
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
CONF = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / "ivan-the-terminal/game-graphics"
STATE = Path(os.environ.get("XDG_STATE_HOME") or HOME / ".local/state") / "ivan-the-terminal/game-graphics"
G = "mcp__claude_ai_Gmail"
DEFAULTS = {"MODEL": "claude-sonnet-5-5", "REPORT_TO": "", "RUN_AT": "17:30"}
PY = Path(sys.executable).with_name("python.exe") if Path(sys.executable).name.lower() == "pythonw.exe" \
    else Path(sys.executable)
sys.path.insert(0, str(TOOLS))


def env(path):
    conf = dict(DEFAULTS)
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r'\s*([A-Z_]+)\s*=\s*"?(.*?)"?\s*(#.*)?$', line)
            if m:
                conf[m.group(1)] = m.group(2)
    return conf


def rule_path(path):
    """Permission-rule form of an absolute path: "//" + the POSIX path, with a Windows drive as /c/..."""
    p = Path(path).as_posix()
    drive, sep, rest = p.partition(":/")
    return f"//{drive.lower()}/{rest}" if sep and len(drive) == 1 else f"/{p}"


def prompt_for(work, to):
    text = (SKILL / "references/prompt.md").read_text(encoding="utf-8")
    profile = (CONF / "profile.md").read_text(encoding="utf-8").strip()
    for key, value in (("{{PROFILE}}", profile), ("{{REPORT_TO}}", to), ("{{WORK}}", work.as_posix()),
                       ("{{TOOLS}}", TOOLS.as_posix()), ("{{SKILL}}", SKILL.as_posix())):
        text = text.replace(key, value)
    return text


def settings_for(work, to):
    guard = shlex.join([str(PY), "-I", TOOLS.joinpath("guard.py").as_posix(), TOOLS.as_posix(), work.as_posix(), to])
    return {"hooks": {"PreToolUse": [{"matcher": "Bash|PowerShell|Monitor|Write|Edit|mcp__claude_ai_Gmail__.*",
                                      "hooks": [{"type": "command", "command": guard}]}]}}


def command(model, settings, work):
    """Least privilege: one helper script, reads of this skill and the work dir, writes to the work dir, mail only
    to the owner. Web pages flow through the run, so the guard (not the model) decides what reaches the disk: the
    helper refuses non-config files, protected folders, anti-cheat games and --force-offline is blocked."""
    tools, work_rule = TOOLS.as_posix(), f"{rule_path(work)}/**"
    allowed = [f"Bash({tools}/run.py:*)", f"Read({work_rule})", f"Edit({work_rule})",
               f"Read({rule_path(SKILL)}/references/**)", "WebSearch", "WebFetch", f"{G}__send_message"]
    disallowed = ["PowerShell", "Monitor", "Agent", "Task", "NotebookEdit", f"{G}__create_draft", f"{G}__reply",
                  f"{G}__forward", f"{G}__update_draft", f"{G}__trash_message", f"{G}__trash_thread"]
    return ["claude", "-p", "--model", model, "--permission-mode", "dontAsk", "--settings", str(settings),
            "--allowedTools", *allowed, "--disallowedTools", *disallowed], allowed


def install_task(run_at):
    if os.name != "nt":
        sys.exit("game-graphics: --install-task is for Windows")
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    q = lambda s: "'" + str(s).replace("'", "''") + "'"
    arg = f'"{Path(__file__).resolve()}" daily'
    ps = (f"$a = New-ScheduledTaskAction -Execute {q(pyw if pyw.exists() else exe)} -Argument {q(arg)} "
          f"-WorkingDirectory {q(HOME)}; "
          f"$t = New-ScheduledTaskTrigger -Daily -At {q(run_at)}; "
          "$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
          "-RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 60); "
          "Register-ScheduledTask -TaskName game-graphics -Action $a -Trigger $t -Settings $s -Force | Out-Null")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    print(f"game-graphics: scheduled daily at {run_at}, or at the next start if the PC was off (Task Scheduler: game-graphics)")
    return 0


def daily(argv):
    if not (CONF / "profile.md").is_file():
        print(f"game-graphics: not configured: create {CONF}/config.env and profile.md (templates in {SKILL}/config.example)")
        return 0
    conf = env(CONF / "config.env")
    to = conf["REPORT_TO"].strip()
    if not to:
        print(f"game-graphics: REPORT_TO missing in {CONF}/config.env", file=sys.stderr)
        return 2
    (STATE / "work").mkdir(parents=True, exist_ok=True)
    (STATE / "logs").mkdir(parents=True, exist_ok=True)
    work, logs = (STATE / "work").resolve(), STATE / "logs"
    for p in work.iterdir():
        shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()
    prompt = prompt_for(work, to)
    settings = STATE / "settings.json"
    settings.write_text(json.dumps(settings_for(work, to), indent=2), encoding="utf-8")
    cmd, allowed = command(conf["MODEL"], settings, work)
    if "--dry-run" in argv:
        unfilled = sum("{{" in line for line in prompt.splitlines())
        print(f"prompt: {len(prompt.encode())} bytes, {unfilled} unfilled placeholders")
        print(f"model: {conf['MODEL']}  report to: {to}  work: {work}  run at: {conf['RUN_AT']} (Windows task)")
        print(f"guard: {settings_for(work, to)['hooks']['PreToolUse'][0]['hooks'][0]['command']}")
        print(f"allowed: {' '.join(allowed)}")
        return 0
    log = logs / f"{datetime.now():%Y-%m-%d_%H%M}.log"
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with open(log, "w", encoding="utf-8") as out:
        try:
            status = subprocess.run(cmd, input=prompt, text=True, encoding="utf-8", stdout=out, stderr=subprocess.STDOUT,
                                    cwd=work, creationflags=no_window).returncode
        except FileNotFoundError as e:
            print(f"game-graphics: {e}", file=out)
            status = 127
    cutoff = time.time() - 30 * 86400
    for old in logs.glob("*.log"):
        if old.stat().st_mtime < cutoff:
            old.unlink()
    return status


def main(argv):
    if sys.stdout:  # None under pythonw (the Windows task)
        sys.stdout.reconfigure(encoding="utf-8")
    if argv[:1] == ["--install-task"]:
        return install_task(env(CONF / "config.env")["RUN_AT"])
    if argv[:1] == ["daily"]:
        return daily(argv[1:])
    import graphics
    return graphics.main(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
