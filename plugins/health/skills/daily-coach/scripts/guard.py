"""PreToolUse guard for the headless daily-coach run. Fails closed: any error blocks the call.

  guard.py TOOLS_DIR WORK_DIR MAIL_TO [WEB_DOMAIN...]

- Gmail: read (search_threads, get_thread, get_message), and send_message only to MAIL_TO with a "Daily plan"
  subject and known fields. Nothing else: no drafts, labels, replies or forwards. Every other MCP tool is blocked
- WebFetch: https only, and only WEB_DOMAINs (and their subdomains) when any are given, so an injected page
  can't make the run send health data to another host
- Write/Edit: only files inside WORK_DIR
- PowerShell, Monitor: never
- Bash: a single `TOOLS_DIR/coach.py <context|checks-set|plan-set|email|has-plan|status> ...` or `date [+FORMAT]`;
  no chaining, substitution or `$`. TOOLS_DIR is written with forward slashes, also on Windows
"""
import json
import re
import shlex
import sys
from pathlib import Path
from urllib.parse import urlparse

SUBCOMMANDS = {"context", "checks-set", "plan-set", "email", "has-plan", "status"}
GMAIL_READ = {"search_threads", "get_thread", "get_message"}
SEND_FIELDS = {"to", "cc", "bcc", "subject", "body", "htmlBody", "html_body"}
SUBJECT = "Daily plan"


def block(reason):
    print(f"Blocked by daily-coach guard: {reason}", file=sys.stderr)
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


def check(tools_dir, work, mail_to, event, domains=()):
    tool = event.get("tool_name", "")
    args = event.get("tool_input") or {}
    if tool.startswith("mcp__claude_ai_Gmail__"):
        name = tool.rsplit("__", 1)[1]
        if name == "send_message":
            if args.get("draftId") or set(args) - SEND_FIELDS:
                block(f"send_message only with {sorted(SEND_FIELDS)}")
            recipients = [a for key in ("to", "cc", "bcc") for a in addresses(args.get(key))]
            if not mail_to or not recipients or any(r != mail_to.lower() for r in recipients):
                block("send_message may only go to the plan's recipient")
            if not str(args.get("subject", "")).startswith(SUBJECT):
                block(f"the plan email's subject starts with {SUBJECT!r} (coach.py email gives it)")
        elif name not in GMAIL_READ:
            block(f"Gmail {name}: this run only reads mail and sends the plan")
    elif tool.startswith("mcp__"):
        block(f"{tool}: this run uses no other MCP tools")
    elif tool == "WebFetch":
        u = urlparse(str(args.get("url", "")))
        host = (u.hostname or "").lower()
        if u.scheme != "https" or not host:
            block("WebFetch: https URLs only")
        if domains and not any(host == d or host.endswith("." + d) for d in domains):
            block(f"WebFetch only on the recipe sites {sorted(domains)}")
    elif tool in ("Write", "Edit"):
        path = Path(str(args.get("file_path", ""))).resolve()
        if Path(work).resolve() not in path.parents:
            block(f"Write/Edit only inside {work}")
    elif tool in ("PowerShell", "Monitor"):
        block(f"{tool} is not available to this run")
    elif tool == "Bash":
        cmd = args.get("command", "")
        if re.search(r"[`\n$]", cmd):  # no `$`: bash's $'..' quoting reads \' differently from shlex
            block("no $, command substitution or multi-line commands")
        lexer = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = ""  # shlex ends a word at a mid-word '#'; bash doesn't: `x#;y` would hide `;y`
        words = list(lexer)
        if not words or any(set(w) <= set("();<>|&") for w in words):
            block("one plain command per call: no pipes, chaining or redirects")
        if words[0] == "date":
            if len(words) > 2 or (len(words) == 2 and not words[1].startswith("+")):
                block("date takes at most a +FORMAT (date -f/-r would read files)")
            return
        coach = f"{tools_dir.rstrip('/')}/coach.py"
        if words[0] != coach or len(words) < 2 or words[1] not in SUBCOMMANDS:
            block(f"Bash may only run {coach} {sorted(SUBCOMMANDS)} or date")


def main():
    try:
        tools_dir, work, mail_to = sys.argv[1], sys.argv[2], sys.argv[3]
        check(tools_dir, work, mail_to, json.load(sys.stdin), tuple(d.lower() for d in sys.argv[4:]))
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 - fail closed
        block(f"guard error ({type(e).__name__}: {e})")
    sys.exit(0)


if __name__ == "__main__":
    main()
