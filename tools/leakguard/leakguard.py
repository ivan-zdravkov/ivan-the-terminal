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
  leakguard.py candidates BASE HEAD  # terms in added lines that *might* be personal (for review)
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
import traceback
import unicodedata
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
ALLOW_FILE = Path(os.environ.get("LEAKGUARD_ALLOW_FILE") or ROOT / ".leakguard-allow")  # CI pins the base branch copy
INLINE_ALLOW = "leakguard:allow"
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff", ".avif", ".dng"}
MEDIA_EXT = {".mov", ".mp4", ".m4v", ".3gp", ".avi", ".mkv"}  # phone videos carry GPS
DOC_EXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp"}  # author metadata, hidden text
OPAQUE_EXT = IMAGE_EXT | MEDIA_EXT | DOC_EXT

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


def _luhn(digits):
    total = sum(d if i % 2 == 0 else (d * 2 - 9 if d > 4 else d * 2) for i, d in enumerate(reversed(digits)))
    return total % 10 == 0


CARD_IIN = re.compile(r"4\d{12}(?:\d{3}){0,2}|(?:5[1-5]\d{2}|222[1-9]|22[3-9]\d|2[3-6]\d{2}|27[01]\d|2720)\d{12}"
                      r"|3[47]\d{13}|6(?:011|5\d{2})\d{12,15}")


def _luhn_ok(m):
    """False positive unless the whole match is a real card: issuer prefix + length + Luhn."""
    digits = re.sub(r"\D", "", m.group(0))
    return not (CARD_IIN.fullmatch(digits) and _luhn([int(c) for c in digits]))


def bank_view(line):
    """Normalise copy-paste artefacts (NBSP, thin spaces, tabs, full-width digits, slashes) for the bank rules."""
    return re.sub(r"[\s/,\u2013\u2014]+", " ", unicodedata.normalize("NFKC", line))


def _account_ok(m):
    return sum(c.isdigit() for c in m.group(0)) < 6


def _iban_ok(m):
    s = re.sub(r"[ -]", "", m.group(0)).upper()
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
    ("iban", re.compile(r"(?i)\b[A-Z]{2} ?\d{2}(?:[ .-]?[A-Z0-9]{4}){3,7}(?:[ .-]?[A-Z0-9]{1,3})?\b"), _iban_ok),
    # card layouts: 4-4-4-4(+), Amex 4-6-5, or contiguous; one consistent separator
    ("payment-card", re.compile(r"(?<![\d.])(?:\d{4}([ -]?)\d{4}\1\d{4}\1\d{1,7}|\d{4}([ -]?)\d{6}\2\d{4,5}|\d{13,19})(?![\d.])"),
     _luhn_ok),
    ("bank-account", re.compile(
        r"(?i)\b(?:(?:iban|sort[\s_-]*code|routing[\s_-]*(?:number|no)|aba|acct|kontonummer|bankkonto|сметка"
        r"|account[\s_-]*(?:number|num|no))\b\.?|account\s*(?=[:=#]))[\"']?\s*(?:(?:[:=#-]|is)\s*){0,2}[\"']?"
        r"(?-i:(?=[A-Z0-9 .-]*\d)[A-Z0-9][A-Z0-9 .-]{4,32}[A-Z0-9])"), _account_ok),
    ("bic", re.compile(r"(?i)\b(?:bic|swift[\s_-]*code|swift)\s*[:=#]\s*(?-i:[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)\b"), None),
    ("wifi-secret", re.compile(r"(?i)\b(?:psk|wpa_passphrase|wifi_?pass(?:word)?)\s*[=:]\s*\S+"), None),
]
HARD_RULES = {"payment-card", "iban", "bank-account", "bic", "private-key", "age-secret-key"}  # no allowlist, no inline allow
TOKEN = re.compile(r"[^\s\"'`<>()\[\]{},;=]+")
SUBTOKEN = re.compile(r"[:/@?&#.+|\\]")


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

    def scan_line(self, where, line, path="", deny_only=False):
        for n, rx in self.deny_plain:
            for m in rx.finditer(line):
                self._report(where, f"denylist#{n}", m.group(0))
        if self.deny_hash:
            for tok in TOKEN.findall(line):
                for cand in {tok, tok.rstrip(".:!?"), *SUBTOKEN.split(tok)}:
                    if hashlib.sha256(cand.encode()).hexdigest() in self.deny_hash:
                        self._report(where, "denylist#sha256", cand)
        if deny_only:
            return
        allowed = INLINE_ALLOW in line or self._path_allowed(path)
        banked = bank_view(line)
        for rule, rx, false_positive in RULES:
            hard = rule in HARD_RULES
            if allowed and not hard:
                continue
            for m in rx.finditer(banked if hard else line):
                if false_positive and false_positive(m):
                    continue
                if not hard and any(a.fullmatch(m.group(0)) for a in self.allow_re):
                    continue
                self._report(where, rule, m.group(0))

    def _path_allowed(self, path):
        return any(fnmatch.fnmatch(path, g) for g in self.allow_paths)

    def scan_text(self, label, text, path="", deny_only=False):
        for i, line in enumerate(text.splitlines(), 1):
            self.scan_line(f"{label}:{i}", line, path, deny_only)

    def scan_blob(self, path, data, where=None, content=True):
        """Scan a file's name and bytes. content=False: only checks a text diff can't see (binary, encodings)."""
        where = where or path
        self.scan_line(f"{where} (path)", path, path)
        ext = Path(path).suffix.lower()
        if not self._path_allowed(path):
            if ext in DOC_EXT:
                self._report(where, "document-file", "office/PDF files carry metadata; publish Markdown instead")
            elif ext in MEDIA_EXT:
                self._report(where, "media-file", "videos carry GPS/device metadata; strip it and allowlist the path")
            elif ext in IMAGE_EXT and _has_metadata(data):
                self._report(where, "image-metadata", "EXIF/XMP present; strip it: exiftool -all= FILE")
        if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
            self.scan_text(where, data.decode("utf-16", "replace"), path)
        elif b"\0" in data[:8192] or ext in OPAQUE_EXT:
            strings = b"\n".join(re.findall(rb"[\x20-\x7e]{4,}", data)).decode()
            self.scan_text(where, strings, path, deny_only=True)
        elif content:
            self.scan_text(where, data.decode("utf-8", "replace"), path)

    def scan_patch(self, patch, prefix=""):
        """Scan added lines of a unified diff (git diff -a -U0 / git log -p). Binary lines are left to scan_blob."""
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
            elif path and not header and raw.startswith("+") and "\0" not in raw \
                    and Path(path).suffix.lower() not in OPAQUE_EXT:
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
    if b"<x:xmpmeta" in data or b"GPSLatitude" in data:
        return True
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return b"eXIf" in data or b"iTXt" in data and b"exif" in data.lower()
    return b"Exif" in data[:65536] or b"EXIF" in data[:65536]


def git(*args, binary=False):
    out = subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=ROOT,
                         capture_output=True, check=True).stdout
    return out if binary else out.decode("utf-8", "replace")


# --text defeats `-diff`/`binary` gitattributes; first-parent diffs make merge commits visible.
DIFF = ("-U0", "--text", "--no-color", "--no-ext-diff", "--no-textconv", "-M", "--diff-filter=ACMRT")


def cmd_staged(g):
    g.scan_patch(git("diff", "--cached", *DIFF))
    for path in git("diff", "--cached", "--name-only", "-M", "--diff-filter=ACMRT", "-z").split("\0"):
        if path:  # names of renames/copies/mode changes have no +++ line; binary content has no text diff
            g.scan_blob(path, git("show", f":{path}", binary=True), content=False)


def cmd_range(g, base, head):
    rng = head if base == "--root" else f"{base}..{head}"
    g.scan_patch(git("log", "-p", *DIFF, "--diff-merges=first-parent", "--format=commit:%H", rng))
    for block in git("log", "--format=%H%x00%B%x01", rng).split("\x01"):
        if "\0" in block:
            sha, msg = block.strip("\n").split("\0", 1)
            g.scan_text(f"{sha[:8]} (message)", msg)
    sha = None
    for line in git("log", "--name-only", "-M", "--diff-filter=ACMRT", "--diff-merges=first-parent",
                    "--format=commit:%H", rng).splitlines():
        if line.startswith("commit:"):
            sha = line[7:]
        elif line and sha:
            g.scan_blob(line, git("cat-file", "blob", f"{sha}:{line}", binary=True), f"{sha[:8]}:{line}", content=False)


def cmd_tree(g):
    for path in git("ls-files", "-z").split("\0"):
        if path and (ROOT / path).is_file():
            g.scan_blob(path, (ROOT / path).read_bytes())


REVIEWED_FILE = ROOT / ".leakguard-reviewed"
WORD = re.compile(r"(?<![\w@./-])[^\W\d_][^\W_]*(?:['-][^\W\d_]+)*")
NUMBERISH = re.compile(r"\b\d{4,}\b|@[\w.-]{3,}")


def cmd_candidates(g, base, head):
    """List terms from a range that a human should classify: capitalised or all-caps words (any script) never seen
    in lowercase in the base tree, long numbers and handles, from added lines, commit messages and file names.
    Skips terms already in .leakguard-reviewed."""
    rng = head if base == "--root" else f"{base}..{head}"
    texts = [l[1:] for l in git("log", "-p", *DIFF, "--diff-merges=first-parent", "--format=", rng).splitlines()
             if l.startswith("+") and not l.startswith("+++")]
    texts += git("log", "--format=%B", rng).splitlines()
    texts += git("log", "--format=", "--name-only", "--diff-merges=first-parent", rng).splitlines()
    corpus = set()
    if base != "--root":  # what the repo already says in lowercase is ordinary vocabulary
        for path in git("ls-tree", "-r", "--name-only", base).splitlines():
            if Path(path).suffix.lower() not in OPAQUE_EXT:
                corpus.update(re.findall(r"\b[^\W\d_]+\b", git("show", f"{base}:{path}").lower()))
    reviewed = set()
    if REVIEWED_FILE.is_file():
        reviewed = {l.strip().casefold() for l in REVIEWED_FILE.read_text().splitlines() if l.strip() and l[0] != "#"}
    counts = {}
    for line in texts:
        terms = [w for w in WORD.findall(line) if w[0].isupper() and len(w) > 2] + NUMBERISH.findall(line)
        for term in terms:
            if term.casefold() in reviewed or term.lower() in corpus:
                continue
            counts[term] = counts.get(term, 0) + 1
    for term, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"{n}\t{term}")
    return 0


def _common_dir(d):
    try:
        out = subprocess.run(["git", "-C", str(d), "rev-parse", "--path-format=absolute", "--git-common-dir",
                              "--show-toplevel"], capture_output=True, text=True, check=True).stdout.split("\n")
        return Path(out[0]).resolve(), Path(out[1]).resolve()
    except (subprocess.CalledProcessError, FileNotFoundError, NotADirectoryError, IndexError):
        return None, None


def _checkout_of(p):
    """Toplevel of the checkout (main or any worktree of this repo) that contains p, else None."""
    path = Path(p).expanduser().resolve()
    try:
        path.relative_to(ROOT)
        return ROOT
    except ValueError:
        pass
    d = path if path.is_dir() else path.parent
    while not d.exists() and d != d.parent:
        d = d.parent
    common, top = _common_dir(d)
    if not common:
        return None
    if common == _common_dir(ROOT)[0] or _is_guarded_checkout(top):
        return top
    return None


def _is_guarded_checkout(top):
    """A separate clone of this repo: same guard script and the same Claude hook wiring."""
    settings = top / ".claude" / "settings.json"
    return (top / "tools" / "leakguard" / "leakguard.py").is_file() and settings.is_file() \
        and "leakguard.py" in settings.read_text(errors="ignore")


def _inside_root(p):
    return _checkout_of(p) is not None


PUBLISHING = re.compile(r"\bgh\s+(?:pr|issue|release|gist|api|repo)\b|\bgit\b[^|;&]*?\s(?:commit|tag|notes|push)\b")
NO_VERIFY = re.compile(r"(?:^|\s)-[a-zA-Z]*n[a-zA-Z]*(?=\s|$)")  # git commit -n == --no-verify


def cmd_claude_hook(g):
    """Block Write/Edit into this repo, or gh/git publishing commands, that would leak."""
    data = json.load(sys.stdin)
    tool, ti = data.get("tool_name", ""), data.get("tool_input") or {}
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        fp = ti.get("file_path") or ti.get("notebook_path") or ""
        top = _checkout_of(fp) if fp else None
        if top is None:
            return 0
        rel = str(Path(fp).expanduser().resolve().relative_to(top))
        if subprocess.run(["git", "check-ignore", "-q", rel], cwd=top).returncode == 0:
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
        git_cmd = re.search(r"\bgit\b[^|;&]*?\s(commit|push)\b([^|;&]*)", cmd)
        if git_cmd and ("--no-verify" in git_cmd.group(2)
                        or git_cmd.group(1) == "commit" and NO_VERIFY.search(git_cmd.group(2))):
            g._report("command", "hook-bypass", "--no-verify / -n skips the leak gates")
        try:
            words = shlex.split(cmd)
        except ValueError:
            words = cmd.split()
        base = Path(data.get("cwd") or ".")
        # Any file the command could upload: --body-file=F, --notes-file F, gist F, "$(cat F)".
        for word in {part for w in words for part in w.split()}:
            value = word.split("=", 1)[1] if word.startswith("-") and "=" in word else word
            value = value.strip("()$<>'\"`")
            if not value or value.startswith("-"):
                continue
            f = (base / value).expanduser()
            if f.is_file() and f.stat().st_size < 1_000_000:
                g.scan_text(value, f.read_text(encoding="utf-8", errors="replace"))
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
    elif cmd == "candidates" and len(rest) == 2:
        return cmd_candidates(g, *rest)
    elif cmd == "claude-hook":
        try:
            return cmd_claude_hook(g)
        except Exception:  # fail closed: a crashing guard must not let the write through
            traceback.print_exc()
            print("leakguard: hook error, blocking to be safe. Fix the hook or the input.", file=sys.stderr)
            return 2
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return g.done()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
