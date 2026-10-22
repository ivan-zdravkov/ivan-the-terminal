"""PreToolUse guard for the headless job digest.

send_message may only go to the allowed recipients (argv); unlabel_thread may only archive (INBOX/UNREAD).
Everything else the digest does to other people is a draft, which the candidate sends by hand.
"""
import json
import sys

allowed = {a.strip().lower() for a in sys.argv[1:] if a.strip()}
event = json.load(sys.stdin)
tool = event.get("tool_name", "")
args = event.get("tool_input", {}) or {}

if tool.endswith("__send_message"):
    recipients = [r for key in ("to", "cc", "bcc") for r in (args.get(key) or [])]
    if not allowed or not recipients or any(r.strip().lower() not in allowed for r in recipients):
        print("Blocked: send_message may only go to the digest recipient. Use create_draft for anything else.",
              file=sys.stderr)
        sys.exit(2)

if tool.endswith("__unlabel_thread"):
    if not set(args.get("labelIds") or []) <= {"INBOX", "UNREAD"}:
        print("Blocked: unlabel_thread may only remove INBOX/UNREAD (archive job alerts).", file=sys.stderr)
        sys.exit(2)
sys.exit(0)
