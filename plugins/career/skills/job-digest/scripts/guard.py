"""PreToolUse guard for the headless job digest. Fails closed: any error blocks the call.

  guard.py TOOLS_DIR WORK_DIR

- send_message / reply / forward: never. The digest goes to the Jobs app; replies are drafts the candidate sends
- create_draft: no attachments (the candidate attaches the CV by hand)
- label_* / unlabel_thread: never TRASH/SPAM; unlabel may only remove INBOX/UNREAD (archive)
- Write/Edit: only files inside WORK_DIR
- Bash: a single call to a helper in TOOLS_DIR (fetch, q, html, jobs history|digest-set|has-digest) or `date`;
  no chaining, redirects or substitution
"""
import json
import re
import shlex
import sys
from pathlib import Path

SYSTEM_LABELS = {"TRASH", "SPAM"}
HELPERS = ("fetch", "q", "html")
JOBS = {"history", "digest-set", "has-digest"}


def block(reason):
    print(f"Blocked by job-digest guard: {reason}", file=sys.stderr)
    sys.exit(2)


def check(tools_dir, work, event):
    tool = event.get("tool_name", "")
    args = event.get("tool_input") or {}
    if tool.endswith(("__send_message", "__reply", "__forward", "__update_draft")):
        block("this run sends no email: the digest is stored for the Jobs app, and replies are drafts")
    elif tool.endswith("__create_draft"):
        if args.get("attachments"):
            block("drafts carry no attachments; the candidate attaches the CV before sending")
    elif tool.endswith(("__label_thread", "__label_message", "__unlabel_thread", "__unlabel_message")):
        labels = args.get("labelIds") or args.get("addLabelIds") or []
        if not isinstance(labels, list) or not all(isinstance(l, str) for l in labels):
            block("labelIds must be a list of strings")
        if SYSTEM_LABELS & set(labels):
            block("TRASH/SPAM are off limits")
        if tool.endswith("__unlabel_thread") and not set(labels) <= {"INBOX", "UNREAD"}:
            block("unlabel_thread may only remove INBOX/UNREAD (archive job alerts)")
    elif tool in ("Write", "Edit"):
        path = Path(str(args.get("file_path", ""))).resolve()
        if Path(work).resolve() not in path.parents:
            block(f"Write/Edit only inside {work}")
    elif tool == "Bash":
        cmd = args.get("command", "")
        if re.search(r"[`\n]|\$[({]", cmd):
            block("no command substitution or multi-line commands")
        lexer = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        words = list(lexer)
        if not words or any(set(w) <= set("();<>|&") for w in words):
            block("one plain command per call: no pipes, chaining or redirects")
        exe = words[0]
        if exe == str(Path(tools_dir) / "jobs"):
            if len(words) < 2 or words[1] not in JOBS:
                block(f"jobs may only run {sorted(JOBS)}")
            return
        helpers = {str(Path(tools_dir) / n) for n in HELPERS}
        if exe not in helpers and exe != "date":
            block(f"Bash may only run {sorted(helpers)}, jobs {sorted(JOBS)} or date")


def main():
    try:
        check(sys.argv[1], sys.argv[2], json.load(sys.stdin))
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 - fail closed
        block(f"guard error ({type(e).__name__}: {e})")
    sys.exit(0)


if __name__ == "__main__":
    main()
