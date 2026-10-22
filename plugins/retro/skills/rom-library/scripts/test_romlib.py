"""Tests for romlib and romsync against a throwaway library."""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "rom-sync" / "scripts"))
import romlib  # noqa: E402
import romsync  # noqa: E402


class Library(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.roms = base / "roms"
        files = {
            "psx/Game A (USA) (Disc 1).chd": 10, "psx/Game A (USA) (Disc 2).chd": 10,
            "psx/Game B (Europe).chd": 10, "psx/Game C (USA).cue": 1, "psx/Game C (USA).bin": 10,
            "nes/Hack Thing.zip": 5, "nes/Game D (USA).zip": 5, "nes/Game D (Europe).zip": 5,
            "nes/readme.txt": 1, "switch/Game E [0100000000010000][v0].nsp": 60_000,
            "switch/Game E [0100000000010800][v65536].nsp": 60_000,
            "switch/Game E [0100000000010800][v131072].nsp": 60_000, "switch/Broken [0100000000011001][v0].nsp": 10,
            "ps3/Some Game/PS3_GAME/USRDIR/EBOOT.BIN": 1,
        }
        for rel, size in files.items():
            p = self.roms / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x" * size)
        conf = base / "config" / "ivan-the-terminal"
        conf.mkdir(parents=True)
        (conf / "retro.conf").write_text(f'ROMS="{self.roms}"\nTARGET_card="{base / "card"}"\nTARGET_card_systems="psx nes"\n')
        (base / "card").mkdir()
        self.env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(base / "config")})
        self.env.start()
        romlib.CONF = conf / "retro.conf"

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def audit(self, system):
        return romlib.audit_system(self.roms / system, "USA,World,Europe")["issues"]

    def test_audit_finds_each_issue_kind(self):
        psx, nes, switch = self.audit("psx"), self.audit("nes"), self.audit("switch")
        self.assertEqual(2, len(psx["disc-without-m3u"]))
        self.assertIn("Game B (Europe).chd", psx["pal-only (50Hz)"])
        self.assertEqual(["Game C (USA).cue"], psx["convert->chd"])
        self.assertEqual(["readme.txt"], nes["junk"])
        self.assertEqual(["Hack Thing.zip"], nes["no-region-tag"])
        self.assertTrue(nes["duplicate-title"])
        self.assertNotIn("pal-only (50Hz)", nes)  # a USA version exists
        self.assertEqual(["Game E [0100000000010800][v65536].nsp"], switch["switch-old-update"])
        self.assertEqual(["Broken [0100000000011001][v0].nsp"], switch["switch-stub"])
        self.assertEqual({}, self.audit("ps3"))

    def test_m3u_apply_moves_discs_and_writes_playlist(self):
        with redirect_stdout(io.StringIO()):
            romlib.cmd_m3u(romlib.load_conf(), "psx", apply=True)
        playlist = self.roms / "psx" / "Game A (USA).m3u"
        self.assertEqual("Game A (USA)/Game A (USA) (Disc 1).chd\nGame A (USA)/Game A (USA) (Disc 2).chd\n",
                         playlist.read_text())
        self.assertTrue((self.roms / "psx" / "Game A (USA)" / "noload.txt").exists())
        self.assertNotIn("disc-without-m3u", self.audit("psx"))

    def test_convert_dry_run_touches_nothing(self):
        before = sorted(p.name for p in (self.roms / "psx").iterdir())
        with redirect_stdout(io.StringIO()), mock.patch("shutil.which", return_value="/usr/bin/chdman"):
            romlib.cmd_convert(romlib.load_conf(), "psx", apply=False, delete_source=False, limit=0)
        self.assertEqual(before, sorted(p.name for p in (self.roms / "psx").iterdir()))

    def test_cue_companions_never_escape_the_folder(self):
        psx = self.roms / "psx"
        outside = Path(self.tmp.name) / "thesis.bin"
        outside.write_bytes(b"precious")
        (psx / "Game C (USA).cue").write_text(
            f'REM COMMENT "{outside}"\nTITLE "../../thesis.bin"\nFILE "../thesis.bin" BINARY\n'
            f'FILE "{outside}" BINARY\nFILE "Game C (USA).bin" BINARY\n  TRACK 01 MODE2/2352\n')
        self.assertEqual([psx / "Game C (USA).bin"], romlib.companions_of(psx / "Game C (USA).cue"))
        self.assertTrue(outside.exists())

    def test_sync_to_directory_target(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(0, romsync.main(["push", "card"]))
        card = Path(self.tmp.name) / "card"
        self.assertTrue((card / "psx" / "Game B (Europe).chd").exists())
        self.assertFalse((card / "switch").exists())
        (card / "nes" / "Old Game (USA).zip").write_bytes(b"x")
        with redirect_stdout(io.StringIO()) as plan:
            romsync.main(["plan", "card"])
        self.assertIn("0 to copy", plan.getvalue())
        self.assertIn("1 extra on device", plan.getvalue())


if __name__ == "__main__":
    unittest.main()
