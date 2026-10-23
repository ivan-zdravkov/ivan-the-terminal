"""PreToolUse guard for the headless daily-coach run. Fails closed: any error blocks the call.

  guard.py TOOLS_DIR WORK_DIR RECIPIENT [WEB_DOMAIN...]

- Gmail: only search_threads (exactly the plan-thread query), get_thread, and send_message to RECIPIENT
- WebFetch: https only, and only WEB_DOMAINs (and their subdomains) when any are given, so an injected page
  can't make the run send health data or mail to another host
- Write/Edit: only files inside WORK_DIR
- Bash: a single `TOOLS_DIR/coach <context|plan-set|email|has-plan|status> ...` or `date`; no chaining or substitution
"""
import json
import re
import shlex
import sys
from pathlib import Path
from urllib.parse import urlparse

TAG = "[daily-coach]"
SEND_FIELDS = {"to", "cc", "bcc", "subject", "body", "htmlBody", "html_body", "includeSignature"}
SEARCH = re.compile(r'subject:"\[daily-coach\]" newer_than:\d{1,2}d')  # full match: no OR/extra terms
SUBCOMMANDS = {"context", "plan-set", "email", "has-plan", "status"}


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


def check(tools_dir, work, recipient, event, domains=()):
    tool = event.get("tool_name", "")
    args = event.get("tool_input") or {}
    if tool.startswith("mcp__") and "Gmail" in tool:
        if tool.endswith("__send_message"):
            if set(args) - SEND_FIELDS:
                block(f"send_message only with {sorted(SEND_FIELDS)}")
            rcpt = [a for key in ("to", "cc", "bcc") for a in addresses(args.get(key))]
            if not rcpt or any(r != recipient for r in rcpt):
                block("the plan email goes to its owner only")
            if TAG not in str(args.get("subject", "")):
                block(f"subject must contain {TAG}")
        elif tool.endswith("__search_threads"):
            if not SEARCH.fullmatch(str(args.get("query", "")).strip()):
                block('search only plan threads, exactly: subject:"[daily-coach]" newer_than:<N>d')
        elif not tool.endswith("__get_thread"):
            block(f"{tool} is not allowed in this run")
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
    elif tool == "Bash":
        cmd = args.get("command", "")
        if re.search(r"[`\n]|\$[({]", cmd):
            block("no command substitution or multi-line commands")
        lexer = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        words = list(lexer)
        if not words or any(set(w) <= set("();<>|&") for w in words):
            block("one plain command per call: no pipes, chaining or redirects")
        if words[0] == "date":
            return
        if words[0] != str(Path(tools_dir) / "coach") or len(words) < 2 or words[1] not in SUBCOMMANDS:
            block(f"Bash may only run {Path(tools_dir) / 'coach'} {sorted(SUBCOMMANDS)} or date")


def main():
    try:
        tools_dir, work, recipient = sys.argv[1], sys.argv[2], sys.argv[3].strip().lower()
        domains = {d.strip().lower().lstrip(".") for d in sys.argv[4:] if d.strip()}
        if not recipient:
            block("no recipient configured")
        check(tools_dir, work, recipient, json.load(sys.stdin), domains)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 - fail closed
        block(f"guard error ({type(e).__name__}: {e})")
    sys.exit(0)


if __name__ == "__main__":
    main()
