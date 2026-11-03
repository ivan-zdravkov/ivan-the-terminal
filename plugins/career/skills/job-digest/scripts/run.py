#!/usr/bin/env python3
"""job-digest: run the daily job digest headless (claude -p) with a fixed tool allowlist and a send guard.
  run.py                 real run (what the timer does): searches, triages Gmail, drafts replies, archives
                         LinkedIn alerts and notifications, emails one digest
  run.py --dry-run       assemble prompt + command and print a summary; runs nothing
  run.py --install-task  Windows: schedule the daily run at RUN_AT via Task Scheduler (Linux: a systemd timer)
Private config: ~/.config/ivan-the-terminal/job-digest/{config.env,profile.md} (see ../config.example)
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
CONF = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / "ivan-the-terminal/job-digest"
STATE = Path(os.environ.get("XDG_STATE_HOME") or HOME / ".local/state") / "ivan-the-terminal/job-digest"
G = "mcp__claude_ai_Gmail"
DEFAULTS = {"MODEL": "claude-sonnet-5-5", "DIGEST_TO": "", "RUN_AT": "16:15"}


def load_webapp():
    spec = importlib.util.spec_from_file_location("webapp", SKILL.parents[3] / "tools/webapp/webapp.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def rule_path(path):
    """Permission-rule form of an absolute path: "//" + the POSIX path, with a Windows drive as /c/..."""
    p = Path(path).as_posix()
    drive, sep, rest = p.partition(":/")
    return f"//{drive.lower()}/{rest}" if sep and len(drive) == 1 else f"/{p}"


def prompt_for(work, to):
    text = (SKILL / "references/prompt.md").read_text(encoding="utf-8")
    profile = (CONF / "profile.md").read_text(encoding="utf-8").strip()
    for key, value in (("{{PROFILE}}", profile), ("{{DIGEST_TO}}", to), ("{{WORK}}", work.as_posix()),
                       ("{{TOOLS}}", TOOLS.as_posix())):
        text = text.replace(key, value)
    return text


def settings_for(work, to):
    guard = shlex.join([sys.executable, "-I", TOOLS.joinpath("guard.py").as_posix(), TOOLS.as_posix(),
                        work.as_posix(), to])  # hooks run in bash, also on Windows (Git Bash)
    return {"hooks": {"PreToolUse": [{"matcher": "Bash|PowerShell|Monitor|Write|Edit|mcp__claude_ai_Gmail__.*",
                                      "hooks": [{"type": "command", "command": guard}]}]}}


def command(model, settings, work):
    """Least privilege: no interpreter, no raw curl, Read/Write only inside WORK, mail only to the digest recipient
    (the guard checks it). Untrusted mail and web pages flow through this run, so anything broader turns a prompt
    injection into code execution, file exfiltration or mail sent in the candidate's name."""
    work_rule, tools = f"{rule_path(work)}/**", TOOLS.as_posix()
    allowed = [f"Bash({tools}/fetch.py:*)", f"Bash({tools}/q.py:*)", f"Bash({tools}/page.py:*)", "Bash(date:*)",
               f"Read({work_rule})", f"Edit({work_rule})", "WebSearch", "WebFetch",
               f"{G}__search_threads", f"{G}__get_thread", f"{G}__get_message", f"{G}__list_labels",
               f"{G}__label_thread", f"{G}__label_message", f"{G}__list_drafts", f"{G}__get_draft",
               f"{G}__create_draft", f"{G}__send_message", f"{G}__unlabel_thread"]
    disallowed = [f"{G}__forward", f"{G}__reply", f"{G}__trash_message", f"{G}__trash_thread",
                  f"{G}__delete_draft", f"{G}__delete_label", f"{G}__mark_message_spam", f"{G}__mark_thread_spam",
                  f"{G}__update_draft", f"{G}__untrash_message", f"{G}__untrash_thread", f"{G}__create_label",
                  f"{G}__update_label", "PowerShell", "Monitor", "Agent", "Task", "NotebookEdit"]
    return ["claude", "-p", "--model", model, "--permission-mode", "dontAsk", "--settings", str(settings),
            "--allowedTools", *allowed, "--disallowedTools", *disallowed], allowed


def install_task(run_at):
    if os.name != "nt":
        sys.exit("job-digest: --install-task is for Windows; Linux uses a systemd timer (job-digest.timer)")
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    q = lambda s: "'" + str(s).replace("'", "''") + "'"
    ps = (f"$a = New-ScheduledTaskAction -Execute {q(pyw if pyw.exists() else exe)} "
          f"-Argument {q(chr(34) + str(Path(__file__).resolve()) + chr(34))} -WorkingDirectory {q(HOME)}; "
          f"$t = New-ScheduledTaskTrigger -Daily -At {q(run_at)}; "
          "$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
          "-RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 45); "
          "Register-ScheduledTask -TaskName job-digest -Action $a -Trigger $t -Settings $s -Force | Out-Null")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    print(f"job-digest: scheduled daily at {run_at}, or at the next start if the PC was off (Task Scheduler: job-digest)")
    return 0


def desktop_notify(title, body):
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", title, body])


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")  # same as the helpers, whatever the Windows code page
    mode = argv[0] if argv else ""
    if not (CONF / "config.env").is_file() or not (CONF / "profile.md").is_file():
        print(f"job-digest: not configured: create {CONF}/config.env and profile.md "
              f"(templates in {SKILL}/config.example)")
        return 0
    conf = load_webapp().env(CONF / "config.env", DEFAULTS)
    model, to = conf["MODEL"], conf["DIGEST_TO"].strip()
    if not to:
        print(f"job-digest: DIGEST_TO missing in {CONF}/config.env", file=sys.stderr)
        return 2
    if mode == "--install-task":
        return install_task(conf["RUN_AT"])

    (STATE / "work").mkdir(parents=True, exist_ok=True)
    (STATE / "logs").mkdir(parents=True, exist_ok=True)
    work, logs = (STATE / "work").resolve(), STATE / "logs"  # resolved: permission rules see real paths
    for p in work.iterdir():
        shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()
    prompt = prompt_for(work, to)
    settings = STATE / "settings.json"
    settings.write_text(json.dumps(settings_for(work, to), indent=2), encoding="utf-8")
    cmd, allowed = command(model, settings, work)

    if mode == "--dry-run":
        unfilled = sum("{{" in line for line in prompt.splitlines())
        print(f"prompt: {len(prompt.encode())} bytes, {unfilled} unfilled placeholders")
        print(f"model: {model}  digest to: {to}  work: {work}  run at: {conf['RUN_AT']} (Windows task)")
        print(f"guard: {settings_for(work, to)['hooks']['PreToolUse'][0]['hooks'][0]['command']}")
        print(f"allowed: {' '.join(allowed)}")
        return 0

    log = logs / f"{datetime.now():%Y-%m-%d_%H%M}.log"
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # the Windows task runs pythonw: no console to flash
    with open(log, "w", encoding="utf-8") as out:
        try:  # cwd = work dir: nothing else is in default read scope; prompt on stdin: not in /proc/*/cmdline
            status = subprocess.run(cmd, input=prompt, text=True, encoding="utf-8", stdout=out, stderr=subprocess.STDOUT,
                                    cwd=work, env={**os.environ, "JOB_DIGEST_WORK": str(work)},
                                    creationflags=no_window).returncode
        except FileNotFoundError as e:
            print(f"job-digest: {e}", file=out)
            status = 127
    if status != 0:
        desktop_notify("Job digest failed", f"See {log}")
    cutoff = time.time() - 30 * 86400
    for old in logs.glob("*.log"):
        if old.stat().st_mtime < cutoff:
            old.unlink()
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
