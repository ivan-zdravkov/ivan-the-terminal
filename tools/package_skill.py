#!/usr/bin/env python3
"""Zip a skill for upload to claude.ai (Customize → Skills → Upload a skill).

  package_skill.py SKILL_DIR [OUT_DIR]      default OUT_DIR: dist/

The zip holds one folder named like the skill, as claude.ai requires. Tests, caches, READMEs and changelogs stay out.
Timestamps are fixed, so the same tree always gives the same zip (and the same sha256).
"""
import hashlib
import sys
import zipfile
from pathlib import Path

SKIP_DIRS = {"__pycache__", ".pytest_cache"}
FIXED = (2026, 1, 1, 0, 0, 0)


def wanted(p):
    return not (SKIP_DIRS & set(p.parts) or p.name.startswith(("test_", ".", "README", "CHANGELOG")) or p.suffix == ".pyc")


def package(skill, out):
    if not (skill / "SKILL.md").is_file():
        raise SystemExit(f"package_skill: {skill} has no SKILL.md")
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"{skill.name}.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(p for p in skill.rglob("*")
                        if p.is_file() and not p.is_symlink() and wanted(p.relative_to(skill))):
            info = zipfile.ZipInfo(f"{skill.name}/{f.relative_to(skill).as_posix()}", FIXED)
            info.external_attr = (0o755 if f.stat().st_mode & 0o100 else 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, f.read_bytes())
    return dest


def main(argv):
    if not 1 <= len(argv) <= 2:
        print(__doc__, file=sys.stderr)
        return 2
    dest = package(Path(argv[0]).resolve(), Path(argv[1] if len(argv) == 2 else "dist"))
    print(f"{dest}  sha256 {hashlib.sha256(dest.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
