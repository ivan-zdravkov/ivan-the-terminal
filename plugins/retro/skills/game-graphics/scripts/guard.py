"""PreToolUse guard for the headless game-graphics run. Fails closed: any error blocks the call.

  guard.py TOOLS_DIR WORK_DIR RECIPIENT

- Bash: one call to TOOLS_DIR/run.py with an allowed subcommand. No chaining, redirects, substitution or `$`.
  Never `daily` (no recursion), `restore`, or `--force-offline`. A plan passed to `apply` must be inside WORK_DIR
- Write/Edit: only files inside WORK_DIR
- PowerShell, Monitor: never
- send_message: only to RECIPIENT, only known fields, plain HTML (no images or styles that load on open)
- any other Gmail tool: never
"""
import json
import re
import shlex
import sys
from html.parser import HTMLParser
from pathlib import Path

SUBCOMMANDS = {"scan", "peek", "apply", "diff", "backups", "optiscaler", "system"}
OPTI = {"latest", "status", "update", "install"}
SEND_FIELDS = {"to", "subject", "body", "htmlBody", "html_body"}
TAGS = {"a", "p", "div", "span", "br", "hr", "b", "strong", "i", "em", "small", "code", "h2", "h3", "h4", "ul", "ol",
        "li", "table", "thead", "tbody", "tr", "td", "th"}
HREF = re.compile(r"https://[^\s\\<>\"'`]*")


class PlainHtml(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.bad = []

    def handle_starttag(self, tag, attrs):
        if tag not in TAGS:
            self.bad.append(f"<{tag}>")
        for k, v in attrs:
            if not (tag == "a" and k == "href" and HREF.fullmatch(v or "")):
                self.bad.append(f"<{tag} {k}=...>")

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag):
        if tag not in TAGS:
            self.bad.append(f"</{tag}>")

    def handle_comment(self, data):
        self.bad.append("comment")

    def handle_decl(self, decl):
        self.bad.append("declaration")

    def unknown_decl(self, data):
        self.bad.append("declaration")

    def handle_pi(self, data):
        self.bad.append("processing instruction")


def block(reason):
    print(f"Blocked by game-graphics guard: {reason}", file=sys.stderr)
    sys.exit(2)


def inside(path, root):
    try:
        p, r = Path(path).resolve(), Path(root).resolve()
    except (OSError, ValueError):
        return False
    return p != r and r in p.parents


def check_bash(cmd, tools, work):
    if re.search(r"[;&|<>`$\n\r]", cmd):
        block("one plain run.py call only (no chaining, redirects, substitution or variables)")
    try:
        argv = shlex.split(cmd)
    except ValueError:
        block("unparseable command")
    run = f"{tools}/run.py"
    if argv[:1] in (["python"], ["python3"], ["py"]):
        argv = argv[1:]
    if not argv or argv[0] != run or len(argv) < 2:
        block(f"only {run} <subcommand> may run")
    sub, rest = argv[1], argv[2:]
    if sub not in SUBCOMMANDS:
        block(f"subcommand {sub!r} not allowed")
    if "--force-offline" in rest:
        block("--force-offline is for a human who knows the game is offline")
    if sub == "optiscaler" and (not rest or rest[0] not in OPTI):
        block("optiscaler: latest, status, update or install only")
    if sub == "apply":
        plans = [a for a in rest if not a.startswith("--")]
        if len(plans) != 1 or not inside(plans[0], work):
            block("apply takes one plan file inside the work dir")


def check_send(inp, recipient):
    unknown = set(inp) - SEND_FIELDS
    if unknown:
        block(f"send_message fields not allowed: {', '.join(sorted(unknown))}")
    to = inp.get("to")
    to = to if isinstance(to, list) else [to]
    if [str(t).strip().lower() for t in to] != [recipient.lower()]:
        block(f"mail only to {recipient}")
    html = inp.get("htmlBody") or inp.get("html_body") or ""
    p = PlainHtml()
    p.feed(html)
    p.close()
    if p.bad:
        block(f"report HTML may only use plain tags and https links: {', '.join(sorted(set(p.bad))[:5])}")


def main(argv):
    try:
        tools, work, recipient = argv[1], argv[2], argv[3]
        event = json.load(sys.stdin)
        name, inp = event.get("tool_name", ""), event.get("tool_input") or {}
        if name in ("PowerShell", "Monitor"):
            block(f"{name} is not allowed")
        if name == "Bash":
            check_bash(inp.get("command", ""), tools, work)
        elif name in ("Write", "Edit"):
            if not inside(inp.get("file_path", ""), work):
                block("writes only inside the work dir")
        elif name.endswith("__send_message"):
            check_send(inp, recipient)
        elif name.startswith("mcp__claude_ai_Gmail__"):
            block(f"{name} is not allowed")
    except SystemExit:
        raise
    except Exception as e:  # fail closed
        block(f"guard error: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
