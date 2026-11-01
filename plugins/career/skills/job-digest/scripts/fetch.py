#!/usr/bin/env -S python3 -I
"""fetch URL NAME: GET a plain https URL into the digest work dir. The headless run's only way to download.

https only, redirects included; at most 20 MB and 20 s; NAME is a plain file name inside $JOB_DIGEST_WORK.
An HTTP error page is saved like curl does, and its status is printed. Stdlib only.
"""
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

URL = re.compile(r"https://[A-Za-z0-9.-]+(:[0-9]+)?(/\S*)?")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
MAX_BYTES, SECONDS = 20_000_000, 20


class HttpsOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).scheme != "https":
            raise urllib.error.URLError(f"redirect to a non-https URL refused: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fail(msg, code=1):
    print(f"fetch: {msg}", file=sys.stderr)
    sys.exit(code)


def main(argv):
    work = os.environ.get("JOB_DIGEST_WORK") or fail("JOB_DIGEST_WORK not set", 2)
    if len(argv) != 2:
        fail("usage: fetch URL NAME", 2)
    url, name = argv
    if not URL.fullmatch(url):
        fail("only plain https URLs", 2)
    if not NAME.fullmatch(name):
        fail("NAME must be a plain file name", 2)
    dest = Path(work) / name
    opener = urllib.request.build_opener(HttpsOnly)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    deadline = time.monotonic() + SECONDS
    try:
        try:
            resp = opener.open(req, timeout=SECONDS)
        except urllib.error.HTTPError as e:
            resp = e  # keep the error page, like curl without -f
        status, size = resp.status, 0
        with resp, open(dest, "wb") as f:
            while chunk := resp.read(65536):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise OSError(f"larger than {MAX_BYTES} bytes")
                if time.monotonic() > deadline:
                    raise TimeoutError(f"took longer than {SECONDS} s")
                f.write(chunk)
    except (OSError, ValueError) as e:  # URLError, timeouts and TLS errors are OSErrors
        dest.unlink(missing_ok=True)
        fail(getattr(e, "reason", None) or e)
    print(f"saved {name} ({size} bytes" + (f", HTTP {status})" if status >= 400 else ")"))


if __name__ == "__main__":
    main(sys.argv[1:])
