"""PreToolUse guard for the headless job digest. Fails closed: any error blocks the call.

  guard.py TOOLS_DIR WORK_DIR RECIPIENT...

- send_message: only to RECIPIENT(s), only known fields; never draftId (that sends a stored draft as-is)
- reply / forward / update_draft: never. Replies to recruiters are drafts the candidate sends
- create_draft: no attachments (the candidate attaches the CV by hand)
- label_* / unlabel_thread: never TRASH/SPAM; unlabel may only remove INBOX/UNREAD (archive)
- Write/Edit: only files inside WORK_DIR
- PowerShell: never
- Bash: a single call to a helper in TOOLS_DIR (fetch.py, q.py, page.py) or `date`;
  no chaining, redirects or substitution. TOOLS_DIR is written with forward slashes, also on Windows
"""
import json
import re
import shlex
import sys
from pathlib import Path

SEND_FIELDS = {"to", "cc", "bcc", "subject", "body", "htmlBody", "html_body", "includeSignature"}
SYSTEM_LABELS = {"TRASH", "SPAM"}
HELPERS = ("fetch.py", "q.py", "page.py")


def block(reason):
    print(f"Blocked by job-digest guard: {reason}", file=sys.stderr)
    sys.exit(2)


def addresses(value):
    items = value if isinstance(value, list) else [value] if value else []
    out = []
    for item in items:
        if not isinstance(item, str):
            block("recipients must be strings")
        for part in item.split(","):
            m = re.search(r"<([^<>]+)>\s*$", part)
            out.append((m.group(1) if m else part).strip().lower())
    return [a for a in out if a]


def check(tools_dir, work, allowed, event):
    tool = event.get("tool_name", "")
    args = event.get("tool_input") or {}
    if tool.endswith("__send_message"):
        if args.get("draftId") or set(args) - SEND_FIELDS:
            block(f"send_message only with {sorted(SEND_FIELDS)}; drafts are sent by the candidate, never here")
        recipients = [a for key in ("to", "cc", "bcc") for a in addresses(args.get(key))]
        if not allowed or not recipients or any(r not in allowed for r in recipients):
            block("send_message may only go to the digest recipient. Use create_draft for anything else.")
    elif tool.endswith(("__reply", "__forward", "__update_draft")):
        block("the only mail this run sends is the digest; replies to recruiters are drafts")
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
            block("unlabel_thread may only remove INBOX/UNREAD (archive)")
    elif tool in ("Write", "Edit"):
        path = Path(str(args.get("file_path", ""))).resolve()
        if Path(work).resolve() not in path.parents:
            block(f"Write/Edit only inside {work}")
    elif tool == "PowerShell":
        block("PowerShell is not available to this run")
    elif tool == "Bash":
        cmd = args.get("command", "")
        if re.search(r"[`\n]|\$[({]", cmd):
            block("no command substitution or multi-line commands")
        lexer = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = ""  # shlex ends a word at a mid-word '#'; bash doesn't: `x#;y` would hide `;y`
        words = list(lexer)
        if not words or any(set(w) <= set("();<>|&") for w in words):
            block("one plain command per call: no pipes, chaining or redirects")
        helpers = {f"{tools_dir.rstrip('/')}/{n}" for n in HELPERS}
        if words[0] not in helpers and words[0] != "date":
            block(f"Bash may only run {sorted(helpers)} or date")


def main():
    try:
        tools_dir, work = sys.argv[1], sys.argv[2]
        allowed = {a.strip().lower() for a in sys.argv[3:] if a.strip()}
        check(tools_dir, work, allowed, json.load(sys.stdin))
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 - fail closed
        block(f"guard error ({type(e).__name__}: {e})")
    sys.exit(0)


if __name__ == "__main__":
    main()
