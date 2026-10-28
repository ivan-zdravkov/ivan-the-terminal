#!/usr/bin/env python3
"""Read time and GPS from photos. Stdlib only, so it runs in any Claude sandbox.

  exif.py PHOTO|ZIP [PHOTO|ZIP...]

Works on JPEG, HEIC/HEIF, PNG and WebP: it finds the embedded TIFF/Exif block instead of parsing each
container. A .zip is read in memory (never extracted): phone apps re-encode photos and drop their metadata,
but they pass archives through untouched. Prints one JSON object: per-photo results plus a summary
(best GPS fix, earliest time, spread).
"""
import json
import math
import struct
import sys
import zipfile
from pathlib import Path

TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}
EXIF_IFD, GPS_IFD = 0x8769, 0x8825
WANT = {0x010F: "make", 0x0110: "model", 0x0132: "datetime", 0x9003: "taken", 0x9011: "offset_taken",
        0x9010: "offset"}
IMAGE_EXT = (".jpg", ".jpeg", ".heic", ".heif", ".png", ".webp", ".dng", ".tif", ".tiff")
MAX_MEMBER = 64 * 1024 * 1024
GPS = {1: "lat_ref", 2: "lat", 3: "lon_ref", 4: "lon", 7: "gps_time", 0x10: "dir_ref", 0x11: "direction",
       0x1D: "gps_date", 0x1F: "accuracy"}


class Tiff:
    def __init__(self, data):
        self.d = data
        self.e = "<" if data[:2] == b"II" else ">"
        if data[:2] not in (b"II", b"MM") or self.u16(2) != 42:
            raise ValueError("not a TIFF header")

    def u16(self, o):
        return struct.unpack_from(self.e + "H", self.d, o)[0]

    def u32(self, o):
        return struct.unpack_from(self.e + "I", self.d, o)[0]

    def value(self, typ, count, off):
        size = TYPE_SIZE.get(typ, 1) * count
        at = off if size <= 4 else self.u32(off)
        raw = self.d[at:at + size]
        if len(raw) < size:
            raise ValueError("truncated value")
        if typ == 2:
            return raw.split(b"\0", 1)[0].decode("utf-8", "replace").strip()
        if typ in (5, 10):
            fmt = self.e + ("I" if typ == 5 else "i") * (2 * count)
            n = struct.unpack(fmt, raw)
            vals = [n[i] / n[i + 1] if n[i + 1] else 0.0 for i in range(0, len(n), 2)]
            return vals if count > 1 else vals[0]
        if typ in (3, 4, 9):
            fmt = self.e + {3: "H", 4: "I", 9: "i"}[typ] * count
            vals = list(struct.unpack(fmt, raw))
            return vals if count > 1 else vals[0]
        return raw

    def ifd(self, off, names):
        out, ptrs = {}, {}
        if off <= 0 or off + 2 > len(self.d):
            return out, ptrs
        for i in range(min(self.u16(off), 512)):
            e = off + 2 + 12 * i
            if e + 12 > len(self.d):
                break
            tag, typ, count = self.u16(e), self.u16(e + 2), self.u32(e + 4)
            try:
                if tag in (EXIF_IFD, GPS_IFD):
                    ptrs[tag] = self.u32(e + 8)
                elif tag in names:
                    out[names[tag]] = self.value(typ, count, e + 8)
            except (ValueError, struct.error):
                continue
        return out, ptrs


def find_tiff(data):
    """The Exif block: after 'Exif\\0\\0' (JPEG APP1, HEIC, WebP) or a bare TIFF header (PNG eXIf)."""
    starts = []
    i = data.find(b"Exif\0\0")
    while i != -1 and len(starts) < 8:
        starts.append(i + 6)
        i = data.find(b"Exif\0\0", i + 1)
    for marker in (b"eXIf", b"EXIF"):  # PNG / WebP chunk ids, payload after the 4-byte length
        j = data.find(marker)
        if j != -1:
            starts += [j + 4, j + 8]
    for s in starts:
        try:
            t = Tiff(data[s:])
            if 8 <= t.u32(4) < len(t.d):
                return t
        except (ValueError, struct.error):
            continue
    return None


def dms(v, ref):
    if isinstance(v, list) and len(v) == 3:
        deg = v[0] + v[1] / 60 + v[2] / 3600
    elif isinstance(v, (int, float)):
        deg = float(v)
    else:
        return None
    return round(-deg if str(ref).upper() in ("S", "W") else deg, 6)


def read_zip(path):
    out = []
    with zipfile.ZipFile(path) as z:
        for m in z.infolist():
            name = m.filename
            if m.is_dir() or "__MACOSX" in name or not name.lower().endswith(IMAGE_EXT):
                continue
            if m.file_size > MAX_MEMBER:
                out.append({"file": f"{path}:{name}", "error": "too large"})
                continue
            out.append(parse(f"{path}:{name}", z.read(m)))
    return out or [{"file": str(path), "warning": "no photos inside the zip"}]


def read_all(path):
    try:
        if zipfile.is_zipfile(path):
            return read_zip(path)
        return [parse(str(path), Path(path).read_bytes())]
    except (OSError, zipfile.BadZipFile, RuntimeError) as e:  # RuntimeError: encrypted zip
        return [{"file": str(path), "error": str(e)}]


def read(path):
    return read_all(path)[0]


def parse(name, data):
    res = {"file": name}
    t = find_tiff(data)
    if not t:
        return res | {"warning": "no Exif metadata: the app or messenger stripped it"}
    main, ptrs = t.ifd(t.u32(4), WANT)
    sub, _ = t.ifd(ptrs.get(EXIF_IFD, 0), WANT)
    gps, _ = t.ifd(ptrs.get(GPS_IFD, 0), GPS)
    info = main | sub
    when = info.get("taken") or info.get("datetime")
    if when and len(when) >= 19 and when[:4] != "0000":
        res["taken_local"] = f"{when[:4]}-{when[5:7]}-{when[8:10]} {when[11:19]}"
        res["utc_offset"] = info.get("offset_taken") or info.get("offset")
    camera = " ".join(x for x in (info.get("make"), info.get("model")) if isinstance(x, str) and x)
    if camera:
        res["camera"] = camera
    lat, lon = dms(gps.get("lat"), gps.get("lat_ref")), dms(gps.get("lon"), gps.get("lon_ref"))
    if lat is not None and lon is not None and (lat, lon) != (0.0, 0.0) and abs(lat) <= 90 and abs(lon) <= 180:
        res["lat"], res["lon"] = lat, lon
        if isinstance(gps.get("accuracy"), float) and gps["accuracy"] > 0:
            res["accuracy_m"] = round(gps["accuracy"])
        if isinstance(gps.get("direction"), float):
            res["facing_deg"] = round(gps["direction"]) % 360
    else:
        res["warning"] = "no GPS in this photo (location was off or the app stripped it)"
    return res


def metres(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def summarize(photos):
    fixes = [p for p in photos if "lat" in p]
    times = sorted(p["taken_local"] for p in photos if "taken_local" in p)
    s = {"photos": len(photos), "with_gps": len(fixes), "with_time": len(times)}
    if fixes:
        best = min(fixes, key=lambda p: p.get("accuracy_m", 999))
        s |= {k: best[k] for k in ("lat", "lon", "accuracy_m") if k in best}
        s["spread_m"] = round(max(metres(best, p) for p in fixes))
    if times:
        s["taken_local"] = times[0]
        s["utc_offset"] = next((p["utc_offset"] for p in photos if p.get("utc_offset")), None)
    cameras = [p["camera"] for p in photos if p.get("camera")]
    if cameras:
        s["camera"] = max(set(cameras), key=cameras.count)
    if not fixes:
        s["next"] = "ask for the address or a map pin; read street signs and house numbers in the photos"
    return s


def main(argv):
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    photos = [r for p in argv for r in read_all(p)]
    print(json.dumps({"summary": summarize(photos), "photos": photos}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
