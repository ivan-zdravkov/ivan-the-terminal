"""envfile: read a skill's private KEY="value" config file into a dict. Stdlib only.

  env(path, defaults)   missing file -> defaults; quoted values keep '#', unquoted ones lose a trailing ' # comment'
"""
import re
from pathlib import Path


def env(path, defaults):
    cfg = dict(defaults)
    if Path(path).is_file():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*([A-Z_]+)=(.*)$", line)
            if not m:
                continue
            raw = m.group(2).strip()
            q = re.match(r"""(["'])(.*?)\1""", raw)
            cfg[m.group(1)] = q.group(2) if q else re.sub(r"\s+#.*$", "", raw)
    return cfg
