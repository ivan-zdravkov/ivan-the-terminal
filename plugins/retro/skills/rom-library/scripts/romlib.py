#!/usr/bin/env python3
"""romlib: audit and tidy an emulation ROM library laid out as <ROMS>/<system>/... (ES-DE style).

  romlib.py audit [SYSTEM...] [--details] [--json]   summary per system; --details lists every issue
  romlib.py convert SYSTEM [--apply] [--delete-source] [--limit N]
                                                     disc images -> CHD (chdman) or RVZ (dolphin-tool)
  romlib.py m3u SYSTEM [--apply]                     playlists for multi-disc sets (discs in "<Title>/" + noload.txt)

Everything is a dry run unless --apply. Sources are only removed with --delete-source, after the output verifies.
Config: ~/.config/ivan-the-terminal/retro.conf (ROMS=..., PREFERRED_REGIONS=...). Stdlib only.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

CONF = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "ivan-the-terminal" / "retro.conf"

# Target format per system for disc-based platforms; cartridge systems keep whatever the emulator reads.
CHD_SYSTEMS = {"psx", "ps2", "psp", "saturn", "segacd", "dreamcast", "pcenginecd", "3do", "neogeocd"}
RVZ_SYSTEMS = {"gc", "wii"}
CHD_SOURCES = {".cue", ".gdi", ".iso", ".toc"}
RVZ_SOURCES = {".iso", ".gcm", ".wbfs", ".ciso", ".gcz"}
PAL_SYSTEMS = {"nes", "snes", "n64", "genesis", "mastersystem", "psx", "ps2", "gc", "wii", "saturn", "dreamcast"}
JUNK_EXT = {".txt", ".nfo", ".url", ".sfv", ".md5", ".sha1", ".html", ".htm", ".diz", ".crdownload", ".part", ".tmp"}
ARCHIVE_EXT = {".7z", ".rar", ".zip"}
ENTRY_SYSTEMS = {"ps3", "wiiu", "xbox360", "psvita"}  # one game = a folder or shortcut + package: count entries only
STUB_BYTES = 50_000  # real DLC can be ~100 KB unlockers; anything this small is a broken download
KEEP_FILES = {"noload.txt", "systeminfo.txt", "gamelist.xml"}
COMPANION_EXT = {".bin", ".img", ".sub", ".ccd", ".raw"}  # belong to a .cue/.gdi/.ccd
REGION = re.compile(r"\((?:[^()]*\b(USA|Europe|Japan|World|Korea|China|Asia|Australia|Brazil|Canada|France|Germany|"
                    r"Italy|Spain|Netherlands|Sweden|UK|En)\b[^()]*)\)")
DISC = re.compile(r"\s*\((?:Disc|Disk|CD)\s*(\d+)(?: of \d+)?\)", re.I)
TAGS = re.compile(r"\s*[\[(][^\])]*[\])]")
SWITCH_ID = re.compile(r"\[([0-9A-Fa-f]{16})\]")
SWITCH_VER = re.compile(r"\[v(\d+)\]")


def load_conf():
    conf = {"ROMS": "", "PREFERRED_REGIONS": "USA,World,Europe"}
    if CONF.is_file():
        for line in CONF.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                conf[key.strip()] = " ".join(shlex.split(value, comments=True))
    if not conf["ROMS"] or not Path(conf["ROMS"]).is_dir():
        sys.exit(f"romlib: ROMS not set or not mounted ({conf['ROMS'] or CONF}). If the drive is missing, run homelab-check.")
    return conf


def title_of(name):
    return TAGS.sub("", Path(name).stem).strip().casefold()


def files_of(system_dir):
    for p in sorted(system_dir.rglob("*")):
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(system_dir).parts):
            yield p


def audit_system(system_dir, regions):
    sysname = system_dir.name
    issues = defaultdict(list)
    if sysname in ENTRY_SYSTEMS:
        entries = [p for p in sorted(system_dir.iterdir()) if not p.name.startswith(".")]
        for p in entries:
            if p.is_file() and (p.suffix.lower() in JUNK_EXT or ".crdownload" in p.name) and p.name not in KEEP_FILES:
                issues["junk"].append(p.name)
        return {"system": sysname, "files": len(entries), "issues": dict(issues), "unit": "entries"}
    files = list(files_of(system_dir))
    by_title = defaultdict(list)
    m3u_refs = set()
    for p in files:
        if p.suffix.lower() == ".m3u":
            for line in p.read_text(errors="ignore").splitlines():
                if line.strip() and not line.startswith("#"):
                    m3u_refs.add((p.parent / line.strip()).resolve())
    for p in files:
        rel = str(p.relative_to(system_dir))
        ext = p.suffix.lower()
        if p.name in KEEP_FILES:
            continue
        if ext in JUNK_EXT or ".crdownload" in p.name:
            issues["junk"].append(rel)
            continue
        if sysname in CHD_SYSTEMS and ext in CHD_SOURCES:
            issues["convert->chd"].append(rel)
        elif sysname in RVZ_SYSTEMS and ext in RVZ_SOURCES:
            issues["convert->rvz"].append(rel)
        if ext in ARCHIVE_EXT and (sysname in CHD_SYSTEMS | RVZ_SYSTEMS or sysname == "switch"):
            issues["archive-to-extract"].append(rel)
        if ext in COMPANION_EXT or ext == ".m3u":
            continue
        if sysname == "switch":
            if p.stat().st_size < STUB_BYTES:
                issues["switch-stub"].append(rel)
            continue
        if DISC.search(p.name):
            if p.resolve() not in m3u_refs:
                issues["disc-without-m3u"].append(rel)
            if p.parent == system_dir:
                issues["disc-not-in-folder"].append(rel)
        if not REGION.search(p.name):
            issues["no-region-tag"].append(rel)
        by_title[title_of(DISC.sub("", p.name))].append(p)
    for title, ps in by_title.items():
        tagged = {m.group(1) for p in ps for m in REGION.finditer(p.name)}
        if sysname in PAL_SYSTEMS and tagged == {"Europe"}:
            issues["pal-only (50Hz)"].append(str(ps[0].relative_to(system_dir)))
        discless = {DISC.sub("", p.stem) for p in ps}
        if len(discless) > 1 and len({p.parent for p in ps}) <= 2:
            issues["duplicate-title"].append(" | ".join(sorted(str(p.relative_to(system_dir)) for p in ps)))
    if sysname == "switch":
        updates = defaultdict(list)
        for p in files:
            tid = SWITCH_ID.search(p.name)
            ver = SWITCH_VER.search(p.name)
            if tid and ver and tid.group(1).upper().endswith("800"):
                updates[tid.group(1).upper()].append((int(ver.group(1)), p))
        for tid, vs in updates.items():
            for _, p in sorted(vs)[:-1]:
                issues["switch-old-update"].append(str(p.relative_to(system_dir)))
    preferred = [r.strip() for r in regions.split(",") if r.strip()]
    return {"system": sysname, "files": len(files), "issues": {k: sorted(v) for k, v in issues.items()},
            "regions": preferred, "unit": "files"}


def cmd_audit(conf, systems, details, as_json):
    root = Path(conf["ROMS"])
    dirs = [root / s for s in systems] if systems else sorted(d for d in root.iterdir() if d.is_dir())
    reports = [audit_system(d, conf["PREFERRED_REGIONS"]) for d in dirs if d.is_dir()]
    if as_json:
        print(json.dumps(reports, indent=1))
        return 0
    total = 0
    for r in reports:
        counts = ", ".join(f"{len(v)} {k}" for k, v in sorted(r["issues"].items()))
        total += sum(len(v) for v in r["issues"].values())
        print(f"{r['system']:<9} {r['files']:>5} {r['unit']:<7} {counts or 'clean'}")
        if details:
            for kind, items in sorted(r["issues"].items()):
                for item in items:
                    print(f"    {kind}: {item}")
    print(f"romlib: {total} issue(s) in {len(reports)} system(s)" + ("" if details else "  (--details to list)"))
    return 0


def companions_of(sheet):
    """Track files a .cue/.gdi references: plain names in the sheet's own folder with an image extension.
    Untrusted input: REM/TITLE lines, absolute paths, ../ and symlinks are never returned."""
    names = []
    for line in sheet.read_text(errors="ignore").splitlines():
        if sheet.suffix.lower() == ".cue":
            m = re.match(r'\s*FILE\s+(?:"([^"]+)"|(\S+))\s+\w+\s*$', line, re.I)
            if m:
                names.append(m.group(1) or m.group(2))
        else:  # gdi: "<track> <lba> <type> <sector> <file> <offset>"
            parts = re.match(r'\s*\d+\s+\d+\s+\d+\s+\d+\s+(?:"([^"]+)"|(\S+))\s+-?\d+\s*$', line)
            if parts:
                names.append(parts.group(1) or parts.group(2))
    out = []
    for name in names:
        if "/" in name or "\\" in name or name.startswith(".") or Path(name).suffix.lower() not in COMPANION_EXT:
            continue
        f = sheet.parent / name
        if f.is_file() and not f.is_symlink() and f.resolve().parent == sheet.parent.resolve():
            out.append(f)
    return out


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def dolphin_tool():
    if shutil.which("dolphin-tool"):
        return ["dolphin-tool"]
    if shutil.which("flatpak") and run(["flatpak", "info", "org.DolphinEmu.dolphin-emu"]).returncode == 0:
        return ["flatpak", "run", "--command=dolphin-tool", "org.DolphinEmu.dolphin-emu"]
    return None


def cmd_convert(conf, system, apply, delete_source, limit):
    sysdir = Path(conf["ROMS"]) / system
    if system in CHD_SYSTEMS:
        sources = [p for p in files_of(sysdir) if p.suffix.lower() in CHD_SOURCES | ARCHIVE_EXT]
        if not shutil.which("chdman"):
            sys.exit("romlib: chdman missing (mame-tools)")
    elif system in RVZ_SYSTEMS:
        sources = [p for p in files_of(sysdir) if p.suffix.lower() in RVZ_SOURCES | ARCHIVE_EXT]
        tool = dolphin_tool()
        if not tool:
            sys.exit("romlib: dolphin-tool missing (Dolphin flatpak or AppImage tools)")
    else:
        sys.exit(f"romlib: no conversion target for '{system}'")
    done = 0
    sources = [p for p in sources if not p.is_symlink()]
    for archive in sources[:limit] if limit else sources:
        out = archive.with_suffix(".chd" if system in CHD_SYSTEMS else ".rvz")
        src, tmp = archive, None
        if out.exists():
            print(f"skip (exists): {out.name}")
            continue
        if not apply:
            print(f"would convert: {archive.relative_to(sysdir)} -> {out.name}")
            continue
        if archive.suffix.lower() in ARCHIVE_EXT:
            if not shutil.which("7z"):
                sys.exit("romlib: 7z missing (p7zip) for archived images")
            tmp = archive.parent / f".romlib-{archive.stem}"
            tmp.mkdir(exist_ok=True)
            if run(["7z", "x", "-y", f"-o{tmp}", str(archive)]).returncode != 0:
                print(f"FAILED: can't extract {archive.name}")
                shutil.rmtree(tmp, ignore_errors=True)
                continue
            inner = [p for p in tmp.rglob("*") if not p.is_symlink()
                     and p.suffix.lower() in (CHD_SOURCES if system in CHD_SYSTEMS else RVZ_SOURCES)]
            if any(p.is_symlink() for p in tmp.rglob("*")):
                print(f"skip: {archive.name} contains symlinks")
                shutil.rmtree(tmp, ignore_errors=True)
                continue
            if len(inner) != 1:
                print(f"skip: {archive.name} holds {len(inner)} disc images")
                shutil.rmtree(tmp, ignore_errors=True)
                continue
            src = inner[0]
        if system in CHD_SYSTEMS:
            mode = "createcd" if src.suffix.lower() in {".cue", ".gdi", ".toc"} else "createdvd"
            extra = ["-hs", "2048"] if system == "psp" else []
            res = run(["chdman", mode, "-i", str(src), "-o", str(out), *extra])
            ok = res.returncode == 0 and run(["chdman", "verify", "-i", str(out)]).returncode == 0
        else:
            res = run([*tool, "convert", "-i", str(src), "-o", str(out), "-f", "rvz", "-c", "zstd", "-l", "5",
                       "-b", "131072"])
            ok = res.returncode == 0 and out.exists() and out.stat().st_size > 0
        if not ok:
            out.unlink(missing_ok=True)
            print(f"FAILED: {archive.name}: {(res.stderr or res.stdout).strip().splitlines()[-1:]}")
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
            continue
        saved = archive.stat().st_size - out.stat().st_size
        print(f"converted: {archive.name} -> {out.name} ({saved / 2**20:+.0f} MiB vs source)")
        done += 1
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
            if delete_source:
                archive.unlink()
            continue
        if delete_source:
            companions = companions_of(src) if src.suffix.lower() in {".cue", ".gdi"} else []
            for f in [src, *companions]:
                f.unlink(missing_ok=True)
    print(f"romlib: {done} converted" if apply else "romlib: dry run, add --apply")
    return 0


def cmd_m3u(conf, system, apply):
    sysdir = Path(conf["ROMS"]) / system
    sets = defaultdict(list)
    for p in files_of(sysdir):
        if DISC.search(p.name) and p.suffix.lower() not in COMPANION_EXT | {".m3u"} | JUNK_EXT:
            sets[DISC.sub("", p.stem)].append(p)
    made = 0
    for title, discs in sorted(sets.items()):
        if len(discs) < 2:
            continue
        playlist = sysdir / f"{title}.m3u"
        folder = sysdir / title
        discs.sort(key=lambda p: int(DISC.search(p.name).group(1)))
        if playlist.exists():
            continue
        moves = [(d, folder / d.name) for d in discs if d.parent != folder]
        if any(new.exists() for _, new in moves) or len({new for _, new in moves}) != len(moves):
            print(f"skip {title}: a disc with the same name already exists in {folder.name}/")
            continue
        if not apply:
            print(f"would create {playlist.name} ({len(discs)} discs{', moving into folder' if moves else ''})")
            continue
        folder.mkdir(exist_ok=True)
        for old, new in moves:
            old.rename(new)
        (folder / "noload.txt").touch()
        playlist.write_text("".join(f"{title}/{d.name}\n" for d in discs), encoding="utf-8", newline="\n")
        print(f"created {playlist.name}")
        made += 1
    print(f"romlib: {made} playlist(s) created" if apply else "romlib: dry run, add --apply")
    return 0


def main(argv):
    flags = {a for a in argv if a.startswith("--")}
    args = [a for a in argv if not a.startswith("--")]
    limit = 0
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])
        args.remove(str(limit))
    if not args:
        print(__doc__)
        return 2
    conf = load_conf()
    cmd, rest = args[0], args[1:]
    if cmd == "audit":
        return cmd_audit(conf, rest, "--details" in flags, "--json" in flags)
    if cmd == "convert" and len(rest) == 1:
        return cmd_convert(conf, rest[0], "--apply" in flags, "--delete-source" in flags, limit)
    if cmd == "m3u" and len(rest) == 1:
        return cmd_m3u(conf, rest[0], "--apply" in flags)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
