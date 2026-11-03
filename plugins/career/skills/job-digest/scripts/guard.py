"""PreToolUse guard for the headless job digest. Fails closed: any error blocks the call.

  guard.py TOOLS_DIR WORK_DIR RECIPIENT...

- send_message: only to RECIPIENT(s), only known fields; never draftId (that sends a stored draft as-is)
- reply / forward / update_draft: never. Replies to recruiters are drafts the candidate sends
- create_draft: no attachments (the candidate attaches the CV by hand)
- label_* / unlabel_thread: never TRASH/SPAM; unlabel may only remove INBOX/UNREAD (archive)
- Write/Edit: only files inside WORK_DIR
- PowerShell, Monitor: never
- Bash: a single call to a helper in TOOLS_DIR (fetch.py, q.py, page.py) or `date [+FORMAT]`;
  no chaining, redirects, substitution or `$`. TOOLS_DIR is written with forward slashes, also on Windows
"""
import json
import re
import shlex
import sys
from html.parser import HTMLParser
from pathlib import Path

SEND_FIELDS = {"to", "cc", "bcc", "subject", "body", "htmlBody", "html_body", "includeSignature"}
SYSTEM_LABELS = {"TRASH", "SPAM"}
HELPERS = ("fetch.py", "q.py", "page.py")
# The digest's HTML: plain structure and https/mailto links only. Anything a mail client fetches on open (images,
# CSS backgrounds, even entity- or escape-obfuscated ones) would carry data out without a click, so no other tag and
# no attribute but <a href> gets through. Parsed, not pattern-matched, so entities are decoded first.
TAGS = {"a", "p", "div", "span", "br", "hr", "b", "strong", "i", "em", "u", "small", "code", "blockquote", "h1", "h2",
        "h3", "h4", "ul", "ol", "li", "table", "thead", "tbody", "tr", "td", "th"}
HREF = re.compile(r"(?:https://|mailto:)[^\s\\<>\"'`]*")


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


def html_problems(s):
    p = PlainHtml()
    p.feed(s)
    p.close()
    return p.bad


def block(reason):
    print(f"Blocked by job-digest guard: {reason}", file=sys.stderr)
    sys.exit(2)


def addresses(value):
    """Plain addresses only: a display name or <...> part is refused rather than parsed."""
    items = value if isinstance(value, list) else [value] if value else []
    if not all(isinstance(i, str) and re.fullmatch(r"[^\s<>,;\"]+@[^\s<>,;\"]+", i.strip()) for i in items):
        block("recipients must be plain addresses, one per entry")
    return [i.strip().lower() for i in items]


def check(tools_dir, work, allowed, event):
    tool = event.get("tool_name", "")
    args = event.get("tool_input") or {}
    if tool.endswith("__send_message"):
        if args.get("draftId") or set(args) - SEND_FIELDS:
            block(f"send_message only with {sorted(SEND_FIELDS)}; drafts are sent by the candidate, never here")
        recipients = [a for key in ("to", "cc", "bcc") for a in addresses(args.get(key))]
        if not allowed or not recipients or any(r not in allowed for r in recipients):
            block("send_message may only go to the digest recipient. Use create_draft for anything else.")
        bad = [x for k in ("htmlBody", "html_body") for x in html_problems(str(args.get(k) or ""))]
        if bad:
            block(f"the digest is plain HTML: tags {sorted(TAGS)}, only <a href=https://...>, no other attributes "
                  f"(found {', '.join(bad[:5])})")
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
        helpers = {f"{tools_dir.rstrip('/')}/{n}" for n in HELPERS}
        if words[0] == "date":
            if len(words) > 2 or (len(words) == 2 and not words[1].startswith("+")):
                block("date takes at most a +FORMAT (date -f/-r would read files)")
        elif words[0] not in helpers:
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
