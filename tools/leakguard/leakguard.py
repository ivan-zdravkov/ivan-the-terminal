#!/usr/bin/env python3
"""leakguard: keep personal data out of a public repository.

Two layers:
  * generic rules - IPs, MACs, phone numbers, home paths, tailnet names,
    private keys, IBANs, coordinates, image metadata
  * a private denylist (names, address, clubs, serials, hashed secrets) that
    never lives in this repo: ~/.config/ivan-the-terminal/leakguard.denylist,
    $LEAKGUARD_DENYLIST (path) or $LEAKGUARD_DENYLIST_CONTENT (CI secret)

Usage:
  leakguard.py [--redact] [--require-denylist] staged           # pre-commit
  leakguard.py [--redact] [--require-denylist] range BASE HEAD  # pre-push / CI (BASE=--root: all history)
  leakguard.py [--redact] [--require-denylist] tree             # all tracked files
  leakguard.py [--redact] [--require-denylist] text [FILE|-]    # messages, PR bodies
  leakguard.py claude-hook      # Claude Code PreToolUse hook (JSON on stdin)

Exit codes: 0 clean, 1 findings, 2 blocked (claude-hook) or usage error.
Stdlib only on purpose: it has to run on a fresh machine before anything else.
"""
import fnmatch
import hashlib
import ipaddress
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path



def _root():
    """Repo being guarded: $LEAKGUARD_ROOT, else the git checkout we run in, else this script's repo."""
    if os.environ.get("LEAKGUARD_ROOT"):
        return Path(os.environ["LEAKGUARD_ROOT"]).resolve()
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True)
        return Path(top.stdout.strip()).resolve()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path(__file__).resolve().parents[2]


ROOT = _root()
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "ivan-the-terminal"
ALLOW_FILE = ROOT / ".leakguard-allow"
INLINE_ALLOW = "leakguard:allow"
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff"}

SAFE_NETS = [ipaddress.ip_network(n) for n in (
    "0.0.0.0/32", "127.0.0.0/8", "255.255.255.255/32",
    "192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24",  # RFC 5737 documentation ranges
)]
SAFE_EMAIL = re.compile(
    r"(?i).*@(?:[\w.-]+\.)?(?:example\.(?:com|org|net)|[\w-]+\.(?:example|invalid|test|localhost))$"
    r"|.*@users\.noreply\.github\.com$|noreply@anthropic\.com$|git@(?:github|gitlab)\.com$"
)


def _ip_ok(m):
    try:
        ip = ipaddress.ip_address(m.group(0))
    except ValueError:
        return True  # 999.1.1.1 is not an address
    return any(ip in n for n in SAFE_NETS)


def _phone_ok(m):
    return not 8 <= sum(c.isdigit() for c in m.group(0)) <= 15


def _iban_ok(m):
    s = m.group(0).replace(" ", "")
    s = s[4:] + s[:4]
    return int("".join(str(int(c, 36)) for c in s)) % 97 != 1


RULES = [  # (id, pattern, is_false_positive)
    ("ipv4", re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?!\w|\.\d)"), _ip_ok),
    ("mac-address", re.compile(r"(?<![\w:-])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![\w:-])"), None),
    ("email", re.compile(r"[\w.%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), lambda m: bool(SAFE_EMAIL.match(m.group(0)))),
    ("phone", re.compile(r"(?<![\w+])\+\d{1,3}[ .-]?(?:\(?\d{1,4}\)?[ .-]?){2,5}\d{2,4}(?!\w)"), _phone_ok),
    ("phone-bg", re.compile(r"(?<![\w+])0(?:8[789]|9[89])\d(?:[ -]?\d){6}(?!\d)"), None),
    ("home-path", re.compile(r"(?:/var)?/home/(?!(?:user|runner|USER|you|me|linuxbrew)\b)[A-Za-z_][\w.-]*"
                             r"|/Users/(?!(?:user|you|me|Shared)\b)[A-Za-z_][\w.-]*"
                             r"|/run/media/[\w.-]+|(?i:C:\\\\?Users\\\\?)(?!user\b)\w+"), None),
    ("mtp-uri", re.compile(r"\bmtp:/{2}\S+"), None),
    ("tailnet", re.compile(r"\b[\w-]+\.ts\.net\b|\bfd7a:115c:a1e0:[0-9a-f:]+"), None),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), None),
    ("age-secret-key", re.compile(r"AGE-SECRET-KEY-1[0-9A-Z]{20,}"), None),
    ("coordinates", re.compile(r"(?<![\w.])-?\d{1,2}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,}(?![\w.])"), None),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b"), _iban_ok),
    ("wifi-secret", re.compile(r"(?i)\b(?:psk|wpa_passphrase|wifi_?pass(?:word)?)\s*[=:]\s*\S+"), None),
]
TOKEN = re.compile(r"[^\s\"'`<>()\[\]{},;=]+")


class Guard:
    def __init__(self, redact=False, require_denylist=False):
        self.redact = redact
        self.findings = []
        self.deny_plain, self.deny_hash = self._load_denylist(require_denylist)
        self.allow_re, self.allow_paths = self._load_allow()

    @staticmethod
    def _load_denylist(required):
        text, sources = "", []
        if os.environ.get("LEAKGUARD_DENYLIST_CONTENT"):
            text += os.environ["LEAKGUARD_DENYLIST_CONTENT"] + "\n"
            sources.append("env")
        path = Path(os.environ.get("LEAKGUARD_DENYLIST") or CONFIG_DIR / "leakguard.denylist")
        if path.is_file():
            text += path.read_text(encoding="utf-8")
            sources.append(str(path))
        plain, hashed = [], set()
        for n, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("sha256:"):
                hashed.add(line[7:].lower())
            elif line.startswith("re:"):
                plain.append((n, re.compile(line[3:])))
            else:
                body = r"\s+".join(re.escape(w) for w in line.split())
                plain.append((n, re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE)))
        if required and not (plain or hashed):
            sys.exit("leakguard: denylist required but none found (run `itt bootstrap`)")
        if not sources:
            print("leakguard: no denylist found, generic rules only", file=sys.stderr)
        return plain, hashed

    @staticmethod
    def _load_allow():
        allow_re, allow_paths = [], []
        if ALLOW_FILE.is_file():
            for line in ALLOW_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("path:"):
                    allow_paths.append(line[5:])
                elif line and not line.startswith("#"):
                    allow_re.append(re.compile(line))
        return allow_re, allow_paths

    def _report(self, where, rule, match):
        self.findings.append(f"{where}: {rule}: {'[redacted]' if self.redact else match}")

    def scan_line(self, where, line, path=""):
        for n, rx in self.deny_plain:
            for m in rx.finditer(line):
                self._report(where, f"denylist#{n}", m.group(0))
        if self.deny_hash:
            for tok in TOKEN.findall(line):
                for cand in {tok, tok.rstrip(".:!?")}:
                    if hashlib.sha256(cand.encode()).hexdigest() in self.deny_hash:
                        self._report(where, "denylist#sha256", cand)
        if INLINE_ALLOW in line or any(fnmatch.fnmatch(path, g) for g in self.allow_paths):
            return
        for rule, rx, false_positive in RULES:
            for m in rx.finditer(line):
                if false_positive and false_positive(m):
                    continue
                if any(a.fullmatch(m.group(0)) for a in self.allow_re):
                    continue
                self._report(where, rule, m.group(0))

    def scan_text(self, label, text, path=""):
        for i, line in enumerate(text.splitlines(), 1):
            self.scan_line(f"{label}:{i}", line, path)

    def scan_blob(self, path, data):
        self.scan_line(f"{path} (path)", path, path)
        if Path(path).suffix.lower() in IMAGE_EXT and _has_metadata(data):
            self._report(path, "image-metadata", "EXIF present; strip it: exiftool -all= FILE")
        if b"\0" in data[:8192]:
            return
        self.scan_text(path, data.decode("utf-8", "replace"), path)

    def scan_patch(self, patch, prefix=""):
        """Scan only added lines of a unified diff (git diff -U0 / git log -p)."""
        path, lineno, header = None, 0, False
        for raw in patch.splitlines():
            if raw.startswith("commit:"):
                prefix = raw[7:15] + ":"
            elif raw.startswith("diff --git "):
                header = True
            elif header and raw.startswith("+++ "):
                p = raw[4:]
                path = None if p == "/dev/null" else p[2:] if p.startswith("b/") else p
                if path:
                    self.scan_line(f"{prefix}{path} (path)", path, path)
            elif raw.startswith("@@"):
                header = False
                lineno = int(re.search(r"\+(\d+)", raw).group(1))
            elif path and not header and raw.startswith("+"):
                self.scan_line(f"{prefix}{path}:{lineno}", raw[1:], path)
                lineno += 1

    def done(self, code=1):
        if not self.findings:
            return 0
        print(f"leakguard: {len(self.findings)} finding(s)", file=sys.stderr)
        for f in self.findings:
            print("  " + f, file=sys.stderr)
        print("Fix: use a placeholder/documentation value, move the data to the private overlay, "
              f"or (generic rules only) mark the line with '{INLINE_ALLOW}' / add to .leakguard-allow.",
              file=sys.stderr)
        return code


def _has_metadata(data):
    if data[:2] == b"\xff\xd8":
        return b"Exif\0\0" in data[:65536]
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return b"eXIf" in data or b"iTXt" in data and b"exif" in data.lower()
    return b"Exif" in data[:65536] or b"EXIF" in data[:65536]


def git(*args, binary=False):
    out = subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=ROOT,
                         capture_output=True, check=True).stdout
    return out if binary else out.decode("utf-8", "replace")


def cmd_staged(g):
    g.scan_patch(git("diff", "--cached", "-U0", "--no-color", "--no-ext-diff", "--diff-filter=ACMR"))
    for path in git("diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines():
        if Path(path).suffix.lower() in IMAGE_EXT and _has_metadata(git("show", f":{path}", binary=True)):
            g._report(path, "image-metadata", "EXIF present; strip it: exiftool -all= FILE")


def cmd_range(g, base, head):
    rng = head if base == "--root" else f"{base}..{head}"
    g.scan_patch(git("log", "-p", "-U0", "--no-color", "--no-ext-diff", "--format=commit:%H", rng))
    for block in git("log", "--format=%H%x00%B%x01", rng).split("\x01"):
        if "\0" in block:
            sha, msg = block.strip("\n").split("\0", 1)
            g.scan_text(f"{sha[:8]} (message)", msg)
    for sha in git("rev-list", rng).split():
        for path in git("diff-tree", "--no-commit-id", "-r", "--name-only", "--diff-filter=AM", sha).splitlines():
            if Path(path).suffix.lower() in IMAGE_EXT:
                if _has_metadata(git("cat-file", "blob", f"{sha}:{path}", binary=True)):
                    g._report(f"{sha[:8]}:{path}", "image-metadata", "EXIF present")


def cmd_tree(g):
    for path in git("ls-files", "-z").split("\0"):
        if path and (ROOT / path).is_file():
            g.scan_blob(path, (ROOT / path).read_bytes())


def _inside_root(p):
    try:
        Path(p).resolve().relative_to(ROOT)
        return True
    except (ValueError, OSError):
        return False


PUBLISHING = re.compile(r"\bgh\s+(?:pr|issue|release|gist|api|repo)\b|\bgit\s+(?:commit|tag|notes)\b")


def cmd_claude_hook(g):
    """Block Write/Edit into this repo, or gh/git publishing commands, that would leak."""
    data = json.load(sys.stdin)
    tool, ti = data.get("tool_name", ""), data.get("tool_input") or {}
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        fp = ti.get("file_path") or ti.get("notebook_path") or ""
        if not _inside_root(fp):
            return 0
        rel = str(Path(fp).resolve().relative_to(ROOT))
        if subprocess.run(["git", "check-ignore", "-q", rel], cwd=ROOT).returncode == 0:
            return 0  # ignored files never reach the remote
        g.scan_line(f"{rel} (path)", rel, rel)
        parts = [ti.get("content"), ti.get("new_string"), ti.get("new_source")]
        parts += [e.get("new_string") for e in ti.get("edits") or []]
        for part in filter(None, parts):
            g.scan_text(rel, part, rel)
    elif tool == "Bash":
        cmd = ti.get("command", "")
        if not PUBLISHING.search(cmd) or not (_inside_root(data.get("cwd", "")) or ROOT.name in cmd):
            return 0
        g.scan_text("command", cmd)
        try:
            words = shlex.split(cmd)
        except ValueError:
            words = []
        for flag, value in zip(words, words[1:]):
            if flag in ("--body-file", "-F", "--file") and Path(value).is_file():
                g.scan_text(value, Path(value).read_text(encoding="utf-8", errors="replace"))
    return g.done(code=2)


def main(argv):
    redact = "--redact" in argv or os.environ.get("CI") == "true"
    required = "--require-denylist" in argv
    args = [a for a in argv if a not in ("--redact", "--require-denylist")]
    if not args:
        print(__doc__, file=sys.stderr)
        return 2
    g = Guard(redact=redact, require_denylist=required)
    cmd, rest = args[0], args[1:]
    if cmd == "staged":
        cmd_staged(g)
    elif cmd == "range" and len(rest) == 2:
        cmd_range(g, *rest)
    elif cmd == "tree":
        cmd_tree(g)
    elif cmd == "text":
        src = rest[0] if rest else "-"
        g.scan_text("text" if src == "-" else src,
                    sys.stdin.read() if src == "-" else Path(src).read_text(encoding="utf-8"))
    elif cmd == "claude-hook":
        return cmd_claude_hook(g)
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return g.done()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
