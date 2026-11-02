"""Tests for addgame: launcher analysis, Steam shortcuts.vdf round trips and Apollo entries. No network."""
import json
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import addgame  # noqa: E402

DRIVER_BAT = r"""@echo off
cd /d "%~dp0"
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
set DRIVERFILE=anticheat.sys
set DRIVERNAME=example-ac
sc.exe create %DRIVERNAME% type= kernel binPath="%CD%\%DRIVERFILE%"
sc start "%DRIVERNAME%"
start /wait .\bin\game.exe
"""


class Launcher(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "Some Game"
        self.dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_exe_is_quoted_and_plain(self):
        exe = self.dir / "game.exe"
        exe.write_bytes(b"MZ")
        info = addgame.analyse(exe)
        self.assertEqual(info["apollo_cmd"], f'"{exe}"')
        self.assertFalse(info["admin"])
        self.assertEqual(info["services"], [])

    def test_batch_with_self_elevation_and_kernel_driver(self):
        bat = self.dir / "!start.bat"
        bat.write_text(DRIVER_BAT, encoding="utf-8")
        info = addgame.analyse(bat)
        self.assertEqual(info["apollo_cmd"], f'cmd /c ""{bat}""')
        self.assertTrue(info["admin"])
        self.assertEqual(info["services"], ["example-ac"])
        self.assertEqual(info["drivers"], [str(self.dir / "anticheat.sys")])

    def test_batch_target_exe_through_variable(self):
        bat = self.dir / "go.bat"
        bat.write_text(DRIVER_BAT.replace(r"start /wait .\bin\game.exe",
                                          "set EXENAME=game.exe\nstart /wait .\\bin\\%EXENAME% -arg"), encoding="utf-8")
        self.assertEqual(addgame.analyse(bat)["target"], str((self.dir / "bin" / "game.exe").resolve()))

    def test_plain_batch_needs_no_admin(self):
        bat = self.dir / "start.cmd"
        bat.write_text("@echo off\nstart game.exe\n", encoding="utf-8")
        info = addgame.analyse(bat)
        self.assertFalse(info["admin"])
        self.assertEqual(info["drivers"], [])


class Matching(unittest.TestCase):
    def search(self, results):
        return lambda term: results.get(term, [])

    def test_abbreviated_folder_name_retries_with_significant_words(self):
        results = {"AC Black Flag Resynced": [(1, "AC/DC Live: Rock Band - Track Pack"), (2, "AC Sailing")],
                   "black flag resynced": [(3, "Assassin's Creed Black Flag Resynced"), (4, "Black Flag Rising")]}
        self.assertEqual(addgame.best_match("AC Black Flag Resynced", self.search(results)),
                         (3, "Assassin's Creed Black Flag Resynced"))

    def test_sequel_number_must_match(self):
        results = {"Forza Horizon 6": [(5, "Forza Horizon 5"), (6, "Forza Horizon 6"), (7, "Forza Horizon")]}
        self.assertEqual(addgame.best_match("Forza Horizon 6", self.search(results)), (6, "Forza Horizon 6"))

    def test_plain_title_beats_dlc(self):
        results = {"Forza Horizon 6": [(8, "Forza Horizon 6 VIP Membership"), (6, "Forza Horizon 6")]}
        self.assertEqual(addgame.best_match("Forza Horizon 6", self.search(results)), (6, "Forza Horizon 6"))

    def test_no_confident_match_is_none(self):
        results = {"Totally Unknown Game": [(9, "Something Else")]}
        self.assertIsNone(addgame.best_match("Totally Unknown Game", self.search(results)))


class Shortcuts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vdf = Path(self.tmp.name) / "shortcuts.vdf"

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip_keeps_existing_entries(self):
        existing = {"0": {"appid": -123, "AppName": "Old Game", "Exe": '"C:\\old.exe"', "LastPlayTime": 1700000000,
                          "tags": {"0": "favorite"}}}
        addgame.write_shortcuts(self.vdf, existing)
        sc = addgame.read_shortcuts(self.vdf)
        uid, entry = addgame.steam_entry("New Game", r"C:\Games\New Game\new.exe")
        addgame.upsert_shortcut(sc, "New Game", entry)
        addgame.write_shortcuts(self.vdf, sc)
        back = addgame.read_shortcuts(self.vdf)
        self.assertEqual(back["0"], existing["0"])
        self.assertEqual(back["1"]["AppName"], "New Game")
        self.assertEqual(back["1"]["appid"] & 0xFFFFFFFF, uid)
        self.assertTrue(uid & 0x80000000)

    def test_upsert_replaces_by_name_and_keeps_history(self):
        sc = {}
        _, first = addgame.steam_entry("Game", r"C:\Games\Game\a.exe")
        addgame.upsert_shortcut(sc, "Game", first)
        sc["0"]["LastPlayTime"] = 42
        _, second = addgame.steam_entry("Game", r"C:\Games\Game\b.exe")
        stored = addgame.upsert_shortcut(sc, "Game", second)
        self.assertEqual(len(sc), 1)
        self.assertEqual(stored["Exe"], '"C:\\Games\\Game\\b.exe"')
        self.assertEqual(stored["LastPlayTime"], 42)
        self.assertEqual(stored["appid"], first["appid"])  # grid art stays attached

    def test_missing_or_empty_file_is_empty(self):
        self.assertEqual(addgame.read_shortcuts(self.vdf), {})
        self.vdf.write_bytes(b"")
        self.assertEqual(addgame.read_shortcuts(self.vdf), {})

    def test_removal_reindexes(self):
        sc = {str(i): {"AppName": f"G{i}", "appid": -i} for i in range(3)}
        del sc["1"]
        addgame.write_shortcuts(self.vdf, sc)
        self.assertEqual(list(addgame.read_shortcuts(self.vdf)), ["0", "1"])


class Apollo(unittest.TestCase):
    def info(self, **kw):
        return {"apollo_cmd": '"C:\\Games\\G\\g.exe"', "dir": "C:\\Games\\G", "admin": False, "services": [], **kw}

    def test_new_entry_has_virtual_display_and_cover(self):
        e = addgame.apollo_entry("G", self.info(), "C:\\cfg\\covers\\x.png", True)
        self.assertEqual(e["cmd"], '"C:\\Games\\G\\g.exe"')
        self.assertTrue(e["virtual-display"])
        self.assertEqual(e["image-path"], "C:\\cfg\\covers\\x.png")
        self.assertNotIn("elevated", e)
        self.assertNotIn("prep-cmd", e)

    def test_admin_and_driver_cleanup(self):
        e = addgame.apollo_entry("G", self.info(admin=True, services=["example-ac"]), None, False)
        self.assertTrue(e["elevated"])
        self.assertEqual(e["prep-cmd"][0]["undo"], 'cmd /c "sc stop example-ac & sc delete example-ac"')
        self.assertTrue(e["prep-cmd"][0]["elevated"])

    def test_upsert_keeps_uuid_and_order(self):
        apps = {"apps": [{"name": "Desktop"}, {"name": "G", "uuid": "KEEP", "cmd": "old"}], "env": {}, "version": 2}
        e = addgame.apollo_entry("G", self.info(), None, True, apps["apps"][1])
        self.assertEqual(addgame.upsert_app(apps, e), "updated")
        self.assertEqual([a["name"] for a in apps["apps"]], ["Desktop", "G"])
        self.assertEqual(apps["apps"][1]["uuid"], "KEEP")
        self.assertEqual(addgame.upsert_app(apps, addgame.apollo_entry("H", self.info(), None, True)), "added")
        json.dumps(apps)


class Config(unittest.TestCase):
    def test_overrides_and_comments(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "add-game.conf"
            f.write_text('STEAM_DIR="D:\\Steam"   # comment\nAPOLLO_VIRTUAL_DISPLAY=0\n', encoding="utf-8")
            conf = addgame.load_conf(f)
        self.assertEqual(conf["STEAM_DIR"], "D:\\Steam")
        self.assertEqual(conf["APOLLO_VIRTUAL_DISPLAY"], "0")
        self.assertIn("APOLLO_CONFIG", conf)

    def test_dotenv_value(self):
        text = '# comment\nOTHER=1\nSTEAMGRIDDB_API_KEY="abc123"\n'
        self.assertEqual(addgame.dotenv_value(text, "STEAMGRIDDB_API_KEY"), "abc123")
        self.assertEqual(addgame.dotenv_value(text, "MISSING"), "")

    def test_key_from_environment_wins(self):
        with unittest.mock.patch.dict("os.environ", {"STEAMGRIDDB_API_KEY": "envkey"}):
            self.assertEqual(addgame.sgdb_key({"SGDB_SECRET": "/nonexistent"}), ("envkey", None))
        with unittest.mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(addgame.sgdb_key({"SGDB_SECRET": ""}), ("", None))
            key, why = addgame.sgdb_key({"SGDB_SECRET": "/nonexistent/x.enc.env"})
            self.assertEqual(key, "")
            self.assertIn("SGDB_SECRET", why)


if __name__ == "__main__":
    unittest.main()
