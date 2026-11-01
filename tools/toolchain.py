"""toolchain.txt: the tools ivan-the-terminal needs and where each OS gets them. Stdlib only.
Read by bin/bootstrap.py, bin/doctor and the prep-windows11-installation-iso skill.
"""
import os
from pathlib import Path

FILE = Path(__file__).resolve().parents[1] / "toolchain.txt"
FIELDS = ("cmd", "brew", "winget", "tier", "win_dir", "purpose")


def read(path=FILE):
    """One dict per tool; "-" columns become None. win_dir keeps its %VARS% (the target expands them)."""
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        row = dict(zip(FIELDS, (line.split(None, 5) + [""] * 6)[:6]))
        rows.append({k: None if v == "-" else v for k, v in row.items()})
    return rows


def package(row, windows=os.name == "nt"):
    """The package that provides ROW's command on this OS, or None when it isn't managed here."""
    return row["winget"] if windows else row["brew"]
