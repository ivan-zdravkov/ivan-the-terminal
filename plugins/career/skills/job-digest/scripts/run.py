#!/usr/bin/env python3
"""job-digest: run the weekday job digest headless (claude -p) with a fixed tool allowlist and a guard.
  run.py            real run (what the timer does): searches, triages Gmail, drafts replies, stores one digest, pushes
  run.py --dry-run  assemble prompt + command and print a summary; runs nothing
  run.py --serve    run the Jobs app server (what job-digest-server.service does)
Private config: ~/.config/ivan-the-terminal/job-digest/{config.env,profile.md} (see ../config.example)
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
CONF = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / "ivan-the-terminal/job-digest"
STATE = Path(os.environ.get("XDG_STATE_HOME") or HOME / ".local/state") / "ivan-the-terminal/job-digest"
G = "mcp__claude_ai_Gmail"


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


def settings_for(work):
    guard = shlex.join([sys.executable, "-I", str(TOOLS / "guard.py"), str(TOOLS), str(work)])
    return {"hooks": {"PreToolUse": [{"matcher": "Bash|Write|Edit|mcp__claude_ai_Gmail__.*",
                                      "hooks": [{"type": "command", "command": guard}]}]}}


def command(model, settings, work):
    """Least privilege: no interpreter, no raw curl, Read/Write only inside WORK, no sending mail at all (the digest
    goes to the Jobs app). Untrusted mail and web pages flow through this run, so anything broader turns a prompt
    injection into code execution, file exfiltration or mail sent in the candidate's name."""
    work_rule = f"/{work}/**"  # "//abs/path" is the permission-rule syntax for an absolute path
    allowed = [f"Bash({TOOLS}/fetch.py:*)", f"Bash({TOOLS}/q.py:*)", f"Bash({TOOLS}/page.py:*)",
               f"Bash({TOOLS}/jobs.py history:*)", f"Bash({TOOLS}/jobs.py digest-set:*)",
               f"Bash({TOOLS}/jobs.py has-digest:*)", "Bash(date:*)",
               f"Read({work_rule})", f"Edit({work_rule})", "WebSearch", "WebFetch",
               f"{G}__search_threads", f"{G}__get_thread", f"{G}__get_message", f"{G}__list_labels",
               f"{G}__label_thread", f"{G}__label_message", f"{G}__list_drafts", f"{G}__get_draft",
               f"{G}__create_draft", f"{G}__unlabel_thread"]
    disallowed = [f"{G}__send_message", f"{G}__forward", f"{G}__reply", f"{G}__trash_message", f"{G}__trash_thread",
                  f"{G}__delete_draft", f"{G}__delete_label", f"{G}__mark_message_spam", f"{G}__mark_thread_spam",
                  f"{G}__update_draft", f"{G}__untrash_message", f"{G}__untrash_thread", f"{G}__create_label",
                  f"{G}__update_label", "NotebookEdit"]
    return ["claude", "-p", "--model", model, "--permission-mode", "dontAsk", "--settings", str(settings),
            "--allowedTools", *allowed, "--disallowedTools", *disallowed], allowed


def clear(directory):
    for p in directory.iterdir():
        shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()


def desktop_notify(title, body):
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", title, body])


def main(argv):
    mode = argv[0] if argv else ""
    if not (CONF / "config.env").is_file() or not (CONF / "profile.md").is_file():
        print(f"job-digest: not configured: create {CONF}/config.env and profile.md "
              f"(templates in {SKILL}/config.example)")
        return 0
    model = load_webapp().env(CONF / "config.env", {"MODEL": "claude-sonnet-5-5"})["MODEL"]

    if mode == "--serve":
        if os.name == "posix":
            os.execv(sys.executable, tool("jobs.py", "serve"))  # same PID for systemd
        return subprocess.run(tool("jobs.py", "serve")).returncode

    (STATE / "work").mkdir(parents=True, exist_ok=True)
    (STATE / "logs").mkdir(parents=True, exist_ok=True)
    work, logs = (STATE / "work").resolve(), STATE / "logs"  # resolved: permission rules see real paths
    clear(work)
    prompt = prompt_for(work)
    settings = STATE / "settings.json"
    settings.write_text(json.dumps(settings_for(work), indent=2), encoding="utf-8")
    cmd, allowed = command(model, settings, work)

    if mode == "--dry-run":
        unfilled = sum("{{" in line for line in prompt.splitlines())
        print(f"prompt: {len(prompt.encode())} bytes, {unfilled} unfilled placeholders")
        print(f"model: {model}  work: {work}")
        print(f"guard: {settings_for(work)['hooks']['PreToolUse'][0]['hooks'][0]['command']}")
        print(f"allowed: {' '.join(allowed)}")
        print("status:")
        status = subprocess.run(tool("jobs.py", "status"), capture_output=True, text=True, encoding="utf-8")
        print("".join(f"  {line}\n" for line in status.stdout.splitlines()), end="")
        sys.stdout.flush()  # the child writes straight to the fd: keep our lines first
        subprocess.run(tool("jobs.py", "url"))
        return 0
    if os.name != "posix":
        print("job-digest: the headless run is POSIX-only for now (Windows needs the PowerShell-tool allowlist)")
        return 2

    log = logs / f"{datetime.now():%Y-%m-%d_%H%M}.log"
    with open(log, "w", encoding="utf-8") as out:
        try:  # cwd = work dir: nothing else is in default read scope; prompt on stdin: not in /proc/*/cmdline
            status = subprocess.run(cmd, input=prompt, text=True, encoding="utf-8", stdout=out, stderr=subprocess.STDOUT,
                                    cwd=work, env={**os.environ, "JOB_DIGEST_WORK": str(work)}).returncode
        except FileNotFoundError as e:
            print(f"job-digest: {e}", file=out)
            status = 127
    if status == 0 and subprocess.run(tool("jobs.py", "has-digest")).returncode != 0:
        status = 3  # finished without storing a digest
    if status == 0:  # best effort: the app shows it either way
        with open(log, "a", encoding="utf-8") as out:
            subprocess.run(tool("jobs.py", "notify"), stdout=out, stderr=subprocess.STDOUT)
    if status != 0:
        desktop_notify("Job digest failed", f"See {log}")
    cutoff = time.time() - 30 * 86400
    for old in logs.glob("*.log"):
        if old.stat().st_mtime < cutoff:
            old.unlink()
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
