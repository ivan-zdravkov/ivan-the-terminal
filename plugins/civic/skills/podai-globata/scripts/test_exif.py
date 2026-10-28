"""Tests for exif.py. Photos are built in memory, so no real image (or its metadata) lives in the repo."""
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exif  # noqa: E402

ASCII, SHORT, LONG, RATIONAL = 2, 3, 4, 5


def rationals(*vals, e="<"):
    return b"".join(struct.pack(e + "II", int(v * 100), 100) for v in vals)


def tiff(ifds, e="<"):
    """ifds: list of entry lists [(tag, type, count, payload | ('ptr', ifd_index))]; IFD 0 comes first."""
    sizes = [2 + 12 * len(es) + 4 + sum((len(p) + 1) & ~1 for *_, p in es if isinstance(p, bytes) and len(p) > 4)
             for es in ifds]
    starts = [8 + sum(sizes[:i]) for i in range(len(ifds))]
    out = (b"II" if e == "<" else b"MM") + struct.pack(e + "HI", 42, 8)
    for i, es in enumerate(ifds):
        data_at = starts[i] + 2 + 12 * len(es) + 4
        head, data = struct.pack(e + "H", len(es)), b""
        for tag, typ, count, p in sorted(es):
            if isinstance(p, tuple):
                p = struct.pack(e + "I", starts[p[1]])
            if len(p) <= 4:
                head += struct.pack(e + "HHI", tag, typ, count) + p.ljust(4, b"\0")
            else:
                head += struct.pack(e + "HHII", tag, typ, count, data_at + len(data))
                data += p + (b"\0" if len(p) % 2 else b"")
        out += head + b"\0\0\0\0" + data
    return out


def sample(gps=True, e="<"):
    ifd0 = [(0x010F, ASCII, 6, b"Phone\0"), (0x8769, LONG, 1, ("ptr", 1))]
    exif_ifd = [(0x9003, ASCII, 20, b"2026:10:26 08:41:07\0"), (0x9011, ASCII, 7, b"+03:00\0")]
    ifds = [ifd0, exif_ifd]
    if gps:
        ifd0.append((0x8825, LONG, 1, ("ptr", 2)))
        ifds.append([(1, ASCII, 2, b"N\0"), (2, RATIONAL, 3, rationals(42, 30, 0, e=e)),
                     (3, ASCII, 2, b"E\0"), (4, RATIONAL, 3, rationals(23, 15, 0, e=e)),
                     (0x11, RATIONAL, 1, rationals(90.5, e=e)), (0x1F, RATIONAL, 1, rationals(6, e=e))])
    return tiff(ifds, e)


def jpeg(t):
    app1 = b"Exif\0\0" + t
    return b"\xff\xd8\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + b"\xff\xd9"


class Exif(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, data):
        p = Path(self.tmp.name) / name
        p.write_bytes(data)
        return p

    def check_full(self, r):
        self.assertEqual("2026-10-26 08:41:07", r["taken_local"])
        self.assertEqual("+03:00", r["utc_offset"])
        self.assertEqual((42.5, 23.25), (r["lat"], r["lon"]))
        self.assertEqual(6, r["accuracy_m"])
        self.assertEqual(90, r["facing_deg"])
        self.assertNotIn("warning", r)

    def test_jpeg_little_and_big_endian(self):
        self.check_full(exif.read(self.write("a.jpg", jpeg(sample()))))
        self.check_full(exif.read(self.write("b.jpg", jpeg(sample(e=">")))))

    def test_heic_style_container(self):  # HEIC keeps 'Exif\0\0' + TIFF inside an item, after a 4-byte offset
        data = b"\0\0\0\x18ftypheic" + b"x" * 300 + b"\0\0\0\x06Exif\0\0" + sample() + b"mdat" * 50
        self.check_full(exif.read(self.write("c.heic", data)))

    def test_png_exif_chunk_has_bare_tiff(self):
        t = sample()
        data = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(t)) + b"eXIf" + t + b"\0\0\0\0IEND"
        self.check_full(exif.read(self.write("d.png", data)))

    def test_no_gps_and_no_exif(self):
        r = exif.read(self.write("e.jpg", jpeg(sample(gps=False))))
        self.assertIn("taken_local", r)
        self.assertNotIn("lat", r)
        self.assertIn("GPS", r["warning"])
        r = exif.read(self.write("f.jpg", b"\xff\xd8\xff\xdb" + b"\0" * 64))
        self.assertIn("stripped", r["warning"])

    def test_garbage_does_not_crash(self):
        for blob in (b"", b"Exif\0\0II*\0\xff\xff\xff\xff", b"Exif\0\0MM\0*\0\0\0\x08\xff\xff" + b"\0" * 20):
            self.assertIn("warning", exif.read(self.write("g.jpg", blob)))

    def test_zip_of_photos_is_read_in_memory(self):
        z = Path(self.tmp.name) / "Archive.zip"
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("IMG_0001.HEIC", b"\0\0\0\x18ftypheic" + b"\0\0\0\x06Exif\0\0" + sample())
            f.writestr("sub/IMG_0002.JPG", jpeg(sample(gps=False)))
            f.writestr("__MACOSX/._IMG_0001.HEIC", b"junk")
            f.writestr("notes.txt", b"hello")
        rs = exif.read_all(z)
        self.assertEqual([f"{z}:IMG_0001.HEIC", f"{z}:sub/IMG_0002.JPG"], [r["file"] for r in rs])
        self.check_full(rs[0])
        self.assertNotIn("lat", rs[1])
        self.assertFalse((Path(self.tmp.name) / "IMG_0001.HEIC").exists())  # nothing extracted to disk
        empty = Path(self.tmp.name) / "empty.zip"
        with zipfile.ZipFile(empty, "w") as f:
            f.writestr("a.txt", b"x")
        self.assertIn("no photos", exif.read_all(empty)[0]["warning"])

    def test_summary_picks_most_accurate_fix_and_earliest_time(self):
        a = {"file": "a", "lat": 42.5, "lon": 23.25, "accuracy_m": 20, "taken_local": "2026-10-26 08:42:00"}
        b = {"file": "b", "lat": 42.5001, "lon": 23.25, "accuracy_m": 5, "taken_local": "2026-10-26 08:41:00",
             "utc_offset": "+03:00"}
        s = exif.summarize([a, b, {"file": "c", "warning": "x"}])
        self.assertEqual((42.5001, 5, 11), (s["lat"], s["accuracy_m"], s["spread_m"]))
        self.assertEqual(("2026-10-26 08:41:00", "+03:00"), (s["taken_local"], s["utc_offset"]))
        self.assertIn("address", exif.summarize([{"file": "c"}])["next"])

    def test_summary_names_the_camera_most_photos_came_from(self):
        s = exif.summarize([{"file": "a", "camera": "Apple iPhone 15"}, {"file": "b", "camera": "Apple iPhone 15"},
                            {"file": "c", "camera": "samsung SM-S911B"}, {"file": "d"}])
        self.assertEqual("Apple iPhone 15", s["camera"])
        self.assertNotIn("camera", exif.summarize([{"file": "d"}]))


if __name__ == "__main__":
    unittest.main()
