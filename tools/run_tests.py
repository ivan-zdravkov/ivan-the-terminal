#!/usr/bin/env python3
"""Run every unit test suite, syntax-check every tracked Python file, and optionally shellcheck the shell scripts.

  run_tests.py [-v] [--shellcheck]

One line per step (-v: full unittest output). Each test directory runs in its own process, because suites set
environment and module state at import time. Stdlib only; Linux and Windows. Exit 1 on any failure.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def tracked():
    out = subprocess.run(["git", "-c", "core.quotePath=false", "ls-files"], cwd=ROOT, capture_output=True,
                         text=True, encoding="utf-8", check=True).stdout
    return [ROOT / p for p in out.splitlines() if (ROOT / p).is_file()]


def first_line(path):
    with open(path, "rb") as f:
        return f.readline(200)


def python_files(files):
    return [f for f in files if f.suffix == ".py" or (f.suffix == "" and first_line(f).startswith(b"#!")
                                                      and b"python" in first_line(f))]


def shell_files(files):
    return [f for f in files if f.suffix in (".sh", ".bash") or (f.suffix == "" and first_line(f).startswith(b"#!")
                                                                  and first_line(f).rstrip().endswith((b"sh", b"bash")))]


def main(args):
    verbose = "-v" in args
    files = tracked()
    failed = []

    bad = []
    for f in python_files(files):
        try:
            compile(f.read_bytes(), str(f), "exec")
        except SyntaxError as e:
            bad.append(f"{f.relative_to(ROOT)}:{e.lineno}: {e.msg}")
    print(f"syntax: {len(python_files(files))} Python files" + (", errors:\n  " + "\n  ".join(bad) if bad else " ok"))
    failed += bad

    for d in sorted({f.parent for f in files if f.name.startswith("test_") and f.suffix == ".py"}):
        cmd = [sys.executable, "-I", "-m", "unittest", "discover", "-v" if verbose else "-q", "-s", str(d)]
        p = subprocess.run(cmd, cwd=ROOT, capture_output=not verbose, text=True, encoding="utf-8", errors="replace")
        rel = d.relative_to(ROOT).as_posix()
        if not verbose:
            print(f"{rel}: {(p.stderr.strip().splitlines() or ['no output'])[-1]}")
            if p.returncode:
                print(p.stderr, end="")
        if p.returncode:
            failed.append(rel)

    if "--shellcheck" in args:
        scripts = shell_files(files)
        if not shutil.which("shellcheck"):
            print("shellcheck: not installed (needed for the shell scripts)")
            failed.append("shellcheck")
        elif scripts:
            p = subprocess.run(["shellcheck", "-x", *[str(s.relative_to(ROOT)) for s in scripts]], cwd=ROOT)
            print(f"shellcheck: {len(scripts)} shell scripts " + ("ok" if p.returncode == 0 else "FAILED"))
            if p.returncode:
                failed.append("shellcheck")

    if failed:
        print(f"run_tests: {len(failed)} failure(s)", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
