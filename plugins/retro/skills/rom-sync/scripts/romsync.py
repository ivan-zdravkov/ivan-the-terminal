#!/usr/bin/env python3
"""romsync: mirror selected systems of the ROM library to a device.

  romsync.py targets                              list configured targets
  romsync.py plan TARGET [SYSTEM...] [--delete]   what would change (default)
  romsync.py push TARGET [SYSTEM...] [--delete]   copy missing/changed files; --delete removes extras on the device

Targets live in ~/.config/ivan-the-terminal/retro.conf:
  TARGET_<name>="adb:/sdcard/Emulation/roms"   (Android over adb, USB debugging on)
  TARGET_<name>="/run/media/<user>/<card>/roms" (any mounted directory: SD card, USB, gvfs MTP path)
  TARGET_<name>_systems="nes snes psx"           default systems for that target
Files are compared by relative path and size. Stdlib only.
"""
import os
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "rom-library" / "scripts"))
from romlib import load_conf  # noqa: E402


def adb(*args, check=True):
    return subprocess.run(["adb", *args], capture_output=True, text=True, check=check)


def local_files(root):
    out = {}
    for p in root.rglob("*"):
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(root).parts):
            out[str(p.relative_to(root))] = p.stat().st_size
    return out


def remote_files(dest, system):
    if dest.startswith("adb:"):
        base = f"{dest[4:].rstrip('/')}/{system}"
        res = adb("shell", f"[ -d {shlex.quote(base)} ] && find {shlex.quote(base)} -type f -exec stat -c '%s %n' {{}} +",
                  check=False)
        out = {}
        for line in res.stdout.splitlines():
            size, _, path = line.partition(" ")
            if path.startswith(base + "/") and size.isdigit():
                out[path[len(base) + 1:]] = int(size)
        return out
    base = Path(dest) / system
    return local_files(base) if base.is_dir() else {}


def copy(dest, system, rel, src):
    if dest.startswith("adb:"):
        target = f"{dest[4:].rstrip('/')}/{system}/{rel}"
        adb("shell", f"mkdir -p {shlex.quote(os.path.dirname(target))}")
        return adb("push", str(src), target, check=False).returncode == 0
    target = Path(dest) / system / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".romsync-part")
    try:
        with open(src, "rb") as fi, open(tmp, "wb") as fo:
            while chunk := fi.read(8 << 20):
                fo.write(chunk)
        tmp.replace(target)
        return True
    except OSError as e:
        print(f"  error: {e}")
        tmp.unlink(missing_ok=True)
        return False


def remove(dest, system, rel):
    if dest.startswith("adb:"):
        adb("shell", f"rm -f {shlex.quote(dest[4:].rstrip('/') + '/' + system + '/' + rel)}", check=False)
    else:
        (Path(dest) / system / rel).unlink(missing_ok=True)


def main(argv):
    flags = {a for a in argv if a.startswith("--")}
    args = [a for a in argv if not a.startswith("--")]
    conf = load_conf()
    targets = {k[7:]: v for k, v in conf.items() if k.startswith("TARGET_") and not k.endswith("_systems")}
    if not args or args[0] == "targets":
        for name, dest in targets.items():
            print(f"{name}: {dest}  systems: {conf.get(f'TARGET_{name}_systems', '(all)')}")
        return 0
    if args[0] not in ("plan", "push") or len(args) < 2 or args[1] not in targets:
        print(__doc__)
        return 2
    mode, name = args[0], args[1]
    dest = targets[name]
    root = Path(conf["ROMS"])
    systems = args[2:] or conf.get(f"TARGET_{name}_systems", "").split() or sorted(d.name for d in root.iterdir() if d.is_dir())
    if dest.startswith("adb:"):
        if adb("get-state", check=False).stdout.strip() != "device":
            sys.exit("romsync: no adb device (plug in, unlock, allow USB debugging)")
    elif not Path(dest).is_dir():
        sys.exit(f"romsync: target directory not mounted: {dest}")
    totals = {"copy": 0, "bytes": 0, "extra": 0, "failed": 0}
    for system in systems:
        src_root = root / system
        if not src_root.is_dir():
            print(f"{system}: not in library, skipped")
            continue
        here, there = local_files(src_root), remote_files(dest, system)
        todo = sorted(rel for rel, size in here.items() if there.get(rel) != size)
        extra = sorted(set(there) - set(here))
        size = sum(here[r] for r in todo)
        print(f"{system}: {len(todo)} to copy ({size / 2**30:.1f} GiB), {len(extra)} extra on device")
        totals["copy"] += len(todo)
        totals["bytes"] += size
        totals["extra"] += len(extra)
        if mode == "push":
            for rel in todo:
                if not copy(dest, system, rel, src_root / rel):
                    totals["failed"] += 1
                    print(f"  FAILED {rel}")
            if "--delete" in flags:
                for rel in extra:
                    remove(dest, system, rel)
        elif "--details" in flags:
            for rel in todo:
                print(f"  + {rel}")
            for rel in extra:
                print(f"  - {rel}")
    verb = "copied" if mode == "push" else "would copy"
    print(f"romsync: {verb} {totals['copy']} file(s), {totals['bytes'] / 2**30:.1f} GiB; "
          f"{totals['extra']} extra on device{' (deleted)' if mode == 'push' and '--delete' in flags else ''}"
          f"{'; ' + str(totals['failed']) + ' failed' if totals['failed'] else ''}")
    return 1 if totals["failed"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
