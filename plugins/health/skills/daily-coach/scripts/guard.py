"""PreToolUse guard for the headless daily-coach run. Fails closed: any error blocks the call.

  guard.py TOOLS_DIR WORK_DIR [WEB_DOMAIN...]

- No MCP tools at all: the plan goes to the Daily app, so the run needs no mail and can't send any
- WebFetch: https only, and only WEB_DOMAINs (and their subdomains) when any are given, so an injected page
  can't make the run send health data to another host
- Write/Edit: only files inside WORK_DIR
- Bash: a single `TOOLS_DIR/coach <context|plan-set|has-plan|status> ...` or `date`; no chaining or substitution
"""
import json
import re
import shlex
import sys
from pathlib import Path
from urllib.parse import urlparse

SUBCOMMANDS = {"context", "plan-set", "has-plan", "status"}


def block(reason):
    print(f"Blocked by daily-coach guard: {reason}", file=sys.stderr)
    sys.exit(2)


def check(tools_dir, work, event, domains=()):
    tool = event.get("tool_name", "")
    args = event.get("tool_input") or {}
    if tool.startswith("mcp__"):
        block(f"{tool}: this run uses no MCP tools (the plan goes to the app, not by mail)")
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
        lexer.commenters = ""  # shlex ends a word at a mid-word '#'; bash doesn't: `x#;y` would hide `;y`
        words = list(lexer)
        if not words or any(set(w) <= set("();<>|&") for w in words):
            block("one plain command per call: no pipes, chaining or redirects")
        if words[0] == "date":
            return
        if words[0] != str(Path(tools_dir) / "coach") or len(words) < 2 or words[1] not in SUBCOMMANDS:
            block(f"Bash may only run {Path(tools_dir) / 'coach'} {sorted(SUBCOMMANDS)} or date")


def main():
    try:
        tools_dir, work = sys.argv[1], sys.argv[2]
        domains = {d.strip().lower().lstrip(".") for d in sys.argv[3:] if d.strip()}
        check(tools_dir, work, json.load(sys.stdin), domains)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 - fail closed
        block(f"guard error ({type(e).__name__}: {e})")
    sys.exit(0)


if __name__ == "__main__":
    main()
