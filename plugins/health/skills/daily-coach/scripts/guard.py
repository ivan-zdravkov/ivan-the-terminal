"""PreToolUse guard for the headless daily-coach run. Fails closed: any error blocks the call.

  guard.py TOOLS_DIR WORK_DIR MAIL_TO [WEB_DOMAIN...]

- Gmail: search_threads only with the one plan-reply query, get_thread, and send_message only with exactly what
  `coach.py email` renders (to MAIL_TO). Nothing else: no drafts, labels, replies or forwards. Other MCP tools: blocked
- WebFetch: https only, and only WEB_DOMAINs (and their subdomains, at least one required), so an injected page
  can't make the run send data to another host
- Write/Edit: only files inside WORK_DIR
- PowerShell, Monitor: never
- Bash: a single `TOOLS_DIR/coach.py <context|checks-set|plan-set|email|has-plan|status> ...` or `date [+FORMAT]`;
  no chaining, substitution or `$`. TOOLS_DIR is written with forward slashes, also on Windows
"""
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

SUBCOMMANDS = {"context", "checks-set", "plan-set", "email", "has-plan", "status"}
SEND_FIELDS = {"to", "subject", "body", "htmlBody"}
# The only search: threads with a plan email that the person wrote in. Another query would let an injected page or
# mail make the run read the rest of the mailbox; thread ids from this search can't be guessed for other threads.
QUERY = 'subject:"Daily plan" from:me newer_than:8d'
SEARCH_FIELDS = {"query", "pageSize", "pageToken", "view"}
# Strict on purpose: urlparse reads "https://evil.example\@good.example/" as good.example, Claude Code's fetch
# (WHATWG URL) as evil.example. No userinfo, backslash or whitespace leaves nothing to disagree about.
SAFE_URL = re.compile(r"https://([a-z0-9-]+(?:\.[a-z0-9-]+)+)(?::\d{1,5})?(?:[/?#][^\s\\@<>\"'`]*)?", re.I)


def block(reason):
    print(f"Blocked by daily-coach guard: {reason}", file=sys.stderr)
    sys.exit(2)


def squash(s):
    return " ".join(str(s or "").split())


def rendered(tools_dir):
    """The email exactly as coach.py renders it from the stored plan: what the one send_message must carry."""
    p = subprocess.run([sys.executable, "-I", "-X", "utf8", f"{tools_dir.rstrip('/')}/coach.py", "email"],
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    if p.returncode:
        block(f"coach.py email failed: {p.stderr.strip()[:200]}")
    return json.loads(p.stdout)


def check(tools_dir, work, mail_to, event, domains=()):
    tool = event.get("tool_name", "")
    args = event.get("tool_input") or {}
    if tool.startswith("mcp__claude_ai_Gmail__"):
        name = tool.rsplit("__", 1)[1]
        if name == "send_message":
            # Pinned to coach.py's rendering: the model can't add recipients, links, images or text of its own.
            if set(args) - SEND_FIELDS:
                block(f"send_message only with {sorted(SEND_FIELDS)}")
            to = args.get("to")
            if not mail_to or (to != mail_to and to != [mail_to]):
                block("send_message goes only to the plan's recipient, as `coach.py email` gives it")
            mail = rendered(tools_dir)
            if mail.get("to") != mail_to or args.get("subject") != mail["subject"] \
                    or squash(args.get("htmlBody")) != squash(mail["html"]) or squash(args.get("body")) != squash(mail["text"]):
                block("send exactly what `coach.py email` printed: to, subject, htmlBody = html, body = text")
        elif name == "search_threads":
            if set(args) - SEARCH_FIELDS or squash(args.get("query")) != QUERY:
                block(f"search_threads only with the query {QUERY}")
        elif name != "get_thread":
            block(f"Gmail {name}: this run only reads its plan threads and sends the plan")
    elif tool.startswith("mcp__"):
        block(f"{tool}: this run uses no other MCP tools")
    elif tool == "WebFetch":
        m = SAFE_URL.fullmatch(str(args.get("url", "")))
        host = m.group(1).lower() if m else ""
        if not host:
            block("WebFetch: plain https:// URLs only (no user@, backslashes or spaces)")
        if not any(host == d or host.endswith("." + d) for d in domains):
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
