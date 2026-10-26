#!/usr/bin/env python3
"""Build a mailto: link that opens the phone's mail app with recipients, subject and body filled in.

  mailto.py < email.json      {"to": [...], "cc": [...], "subject": "...", "body": "..."}

Prints the link, then a warning on stderr if it is long enough that some mail apps may cut the body.
Attachments can't travel in a mailto: link; the sender adds the photos in the mail app.
"""
import json
import re
import sys
from urllib.parse import quote

EMAIL = re.compile(r"^[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")  # no ? & = %: they'd smuggle URL params
LONG = 8000


def build(msg):
    to, cc = msg.get("to") or [], msg.get("cc") or []
    bad = [a for a in to + cc if not EMAIL.match(a)]
    if not to or bad:
        raise ValueError(f"need at least one valid 'to' address; invalid: {bad}")
    body = msg.get("body", "").replace("\r\n", "\n").replace("\n", "\r\n")
    params = [("cc", ",".join(cc))] if cc else []
    params += [("subject", msg.get("subject", "")), ("body", body)]
    query = "&".join(f"{k}={quote(v, safe='')}" for k, v in params if v)
    return f"mailto:{','.join(to)}?{query}"


def main():
    try:
        link = build(json.load(sys.stdin))
    except (ValueError, json.JSONDecodeError) as e:
        print(f"mailto: {e}", file=sys.stderr)
        return 2
    print(link)
    if len(link) > LONG:
        print(f"mailto: link is {len(link)} chars; if the body arrives cut, paste the text instead", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
