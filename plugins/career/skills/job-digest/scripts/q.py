#!/usr/bin/env -S python3 -I
"""q [-s] NAME FILTER: run jq -r on a file in the digest work dir (no other files, no env, no modules). Stdlib only."""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
BLOCKED = ("import", "include", "$ENV", "env", "$__", "input")  # jq features that reach files or the environment


def fail(msg):
    print(f"q: {msg}", file=sys.stderr)
    sys.exit(2)


def main(argv):
    work = os.environ.get("JOB_DIGEST_WORK") or fail("JOB_DIGEST_WORK not set")
    opts = ["-r"]
    if argv[:1] == ["-s"]:
        opts.append("-s")
        argv = argv[1:]
    if len(argv) != 2:
        fail("usage: q [-s] NAME FILTER")
    name, jq_filter = argv
    if not NAME.fullmatch(name):
        fail("NAME must be a file in the work dir")
    if any(b in jq_filter for b in BLOCKED):
        fail("filter uses a blocked jq feature")
    jq = shutil.which("jq") or fail("jq is not installed")
    sys.exit(subprocess.run([jq, *opts, "--", jq_filter, str(Path(work) / name)]).returncode)


if __name__ == "__main__":
    main(sys.argv[1:])
