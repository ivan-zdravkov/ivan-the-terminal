import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
TMP = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = str(Path(TMP) / "config")
os.environ["XDG_STATE_HOME"] = str(Path(TMP) / "state")
sys.path.insert(0, str(HERE))
import graphics  # noqa: E402

COD = ("// Enable Variable Rate Shading\nVRS@0;57752;20945 = true\n"
       "AATechniquePreferredMP@0;47961;48403 = SMAA // one of SMAA, XeSS, FSR AA\n"
       "MaxFpsInGame@0;13305;58861 = 250 // 30 to 300\n")


class Editors(unittest.TestCase):
    def test_ini_replace_add_and_new_section(self):
        text = "top=1\r\n[Display]\r\nVSync = 1\r\n\r\n[Feature]\r\nfps=60\r\n"
        new = graphics.edit_ini(text, {"Display": {"VSync": "0", "HDR": "1"}, "Extra": {"k": "v"}, "": {"top": "2"}})
        self.assertIn("VSync = 0\r\nHDR=1\r\n\r\n[Feature]", new)
        self.assertTrue(new.startswith("top=2\r\n"))
        self.assertTrue(new.rstrip().endswith("[Extra]\r\nk=v"))
        self.assertIn("fps=60", new)

    def test_ini_section_case_and_idempotent(self):
        text = "[display]\nA=1\n"
        once = graphics.edit_ini(text, {"Display": {"A": "2"}})
        self.assertEqual(once, "[display]\nA=2\n")
        self.assertEqual(graphics.edit_ini(once, {"Display": {"A": "2"}}), once)

    def test_wtf(self):
        new = graphics.edit_wtf('SET vsync "1"\nSET farclip "7000"\n', {"vsync": "0", "maxFPS": "120"})
        self.assertEqual(new, 'SET vsync "0"\nSET farclip "7000"\nSET maxFPS "120"\n')

    def test_cod_validates_choices_and_range(self):
        new = graphics.edit_cod(COD, {"VRS@0": "false", "AATechniquePreferredMP": "FSR AA", "MaxFpsInGame": "120"})
        self.assertIn("VRS@0;57752;20945 = false\n", new)
        self.assertIn("= FSR AA // one of SMAA, XeSS, FSR AA", new)
        self.assertIn("= 120 // 30 to 300", new)
        with self.assertRaisesRegex(ValueError, "not one of"):
            graphics.edit_cod(COD, {"AATechniquePreferredMP": "TAA"})
        with self.assertRaisesRegex(ValueError, "outside"):
            graphics.edit_cod(COD, {"MaxFpsInGame": "500"})
        with self.assertRaisesRegex(ValueError, "can't be added"):
            graphics.edit_cod(COD, {"Nope@0": "1"})

    def test_forza(self):
        text = '<s>\n<option id="EnableHDR" value="0"/>\n<ShowFPS isDynamic="0" name="Default" value="1"/>\n</s>'
        new = graphics.edit_forza(text, {"EnableHDR": "1", "ShowFPS": "0"})
        self.assertIn('<option id="EnableHDR" value="1"/>', new)
        self.assertIn('name="Default" value="0"/>', new)
        with self.assertRaises(ValueError):
            graphics.edit_forza(text, {"Missing": "1"})

    def test_json(self):
        self.assertEqual(json.loads(graphics.edit_json('{"a": {"b": 1}}', {"a.b": 2, "c.d": "x"})),
                         {"a": {"b": 2}, "c": {"d": "x"}})


class Paths(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.game = self.root / "Games/Some Game"
        self.game.mkdir(parents=True)
        (self.game / "settings.ini").write_text("[a]\nb=1\n", encoding="utf-8")
        (self.game / "game.exe").write_bytes(b"MZ")
        (self.game / "bin.cfg").write_bytes(b"\x00\x01binary")
        (self.root / "elsewhere.ini").write_text("x=1", encoding="utf-8")
        self.games = [{"dir": str(self.game)}]

    def test_game_config_ok(self):
        p, why = graphics.check_path(self.game / "settings.ini", self.games)
        self.assertEqual(why, "")
        self.assertEqual(p, (self.game / "settings.ini").resolve())

    def test_rejects(self):
        for f, msg in ((self.game / "game.exe", "not a config"), (self.game / "bin.cfg", "binary"),
                       (self.root / "elsewhere.ini", ""), (self.game / "nope.ini", "does not exist")):
            why = graphics.check_path(f, self.games)[1]
            self.assertIn(msg, why)
            self.assertTrue(why, f)  # elsewhere.ini: "outside" on Linux, "protected" (Temp under AppData) on Windows

    def test_protected_folder_under_appdata(self):
        if not graphics.WIN:
            self.skipTest("AppData roots are Windows")
        local = Path(tempfile.mkdtemp())
        (local / "Google/Chrome").mkdir(parents=True)
        (local / "Google/Chrome/prefs.json").write_text("{}", encoding="utf-8")
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(local)}):
            self.assertIn("protected", graphics.check_path(local / "Google/Chrome/prefs.json", [])[1])

    def test_appdata_only_game_folders(self):
        if not graphics.WIN:
            self.skipTest("AppData roots are Windows")
        local = Path(tempfile.mkdtemp())
        for rel in ("ForzaHorizon6/cfg/User.xml", "Activision/players/s.txt", "rclone/rclone.conf", "loose.ini"):
            (local / rel).parent.mkdir(parents=True, exist_ok=True)
            (local / rel).write_text("x=1", encoding="utf-8")
        games = [{"name": "Forza Horizon 6", "dir": str(self.game)}]
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(local)}):
            self.assertEqual(graphics.check_path(local / "ForzaHorizon6/cfg/User.xml", games)[1], "")
            self.assertEqual(graphics.check_path(local / "Activision/players/s.txt", games)[1], "")
            self.assertIn("not a scanned game", graphics.check_path(local / "rclone/rclone.conf", games)[1])
            self.assertIn("not a scanned game", graphics.check_path(local / "loose.ini", games)[1])

    def test_bom_roundtrip(self):
        f = self.game / "u16.ini"
        f.write_bytes("[a]\r\nb=1\r\n".encode("utf-16"))
        text, enc = graphics.read_text(f)
        graphics.write_text(f, graphics.edit_ini(text, {"a": {"b": "2"}}), enc)
        self.assertEqual(f.read_bytes().decode("utf-16"), "[a]\r\nb=2\r\n")


class Fingerprint(unittest.TestCase):
    def test_tech_anticheat_and_proxies(self):
        d = Path(tempfile.mkdtemp()) / "G"
        (d / "EasyAntiCheat").mkdir(parents=True)
        for n in ("Game.exe", "amd_fidelityfx_upscaler_dx12.dll", "nvngx_dlss.dll", "winmm.dll", "unins000.exe",
                  "SFX_Ricochet.bank"):
            (d / n).write_bytes(b"x" * (100 if n == "Game.exe" else 1))
        g = graphics.fingerprint({"name": "Some Game", "source": "folder", "dir": str(d)})
        self.assertEqual(g["slug"], "some-game")
        self.assertEqual(Path(g["exe"]).name, "Game.exe")
        self.assertEqual(g["tech"], ["dlss", "fsr3.1"])
        self.assertEqual(g["anticheat"], ["EasyAntiCheat"])
        self.assertEqual(list(g["proxies"].values()), [["winmm.dll"]])


class OptiScaler(unittest.TestCase):
    def setUp(self):
        self.src = Path(tempfile.mkdtemp())
        for n in ("OptiScaler.dll", "OptiScaler.ini", "amd_fidelityfx_dx12.dll", "setup_windows.bat"):
            (self.src / n).write_text(f"new {n}" if n != "OptiScaler.ini" else "[FSR]\nFsr4Update=auto\n",
                                      encoding="utf-8")
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "game.exe").write_bytes(b"MZ")
        (self.dir / "winmm.dll").write_text("loader", encoding="utf-8")
        (self.dir / "amd_fidelityfx_dx12.dll").write_text("old", encoding="utf-8")
        self.game = {"slug": "g", "name": "G", "dir": str(self.dir), "exe": str(self.dir / "game.exe"), "anticheat": []}
        self.rel = {"tag": "v1", "name": "x.7z", "url": "", "sha256": ""}

    def test_install_and_remove_restore_originals(self):
        with mock.patch.object(graphics, "opti_fetch", return_value=self.src), redirect():
            graphics.opti_install(self.game, self.rel, sets={"FSR": {"Fsr4Update": "true"}})
        self.assertEqual((self.dir / "dxgi.dll").read_text(encoding="utf-8"), "new OptiScaler.dll")  # winmm taken
        self.assertEqual((self.dir / "winmm.dll").read_text(encoding="utf-8"), "loader")
        self.assertFalse((self.dir / "setup_windows.bat").exists())
        self.assertIn("Fsr4Update=true", (self.dir / "OptiScaler.ini").read_text(encoding="utf-8"))
        with redirect():
            graphics.opti_remove(self.game)
        self.assertFalse((self.dir / "dxgi.dll").exists())
        self.assertEqual((self.dir / "amd_fidelityfx_dx12.dll").read_text(encoding="utf-8"), "old")
        self.assertEqual((self.dir / "winmm.dll").read_text(encoding="utf-8"), "loader")

    def test_refuses_anticheat_online_and_taken_proxy(self):
        with mock.patch.object(graphics, "opti_fetch", return_value=self.src):
            with self.assertRaisesRegex(RuntimeError, "anti-cheat"):
                graphics.opti_install({**self.game, "anticheat": ["BEService.exe"]}, self.rel)
            with self.assertRaisesRegex(RuntimeError, "online"):
                graphics.opti_install({**self.game, "online": True}, self.rel, force_offline=True)
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                graphics.opti_install(self.game, self.rel, proxy="winmm.dll")


class Guard(unittest.TestCase):
    TOOLS, WORK, TO = "C:/s/scripts", str(Path(TMP) / "work"), "me@example.com"

    def run_guard(self, name, inp):
        event = json.dumps({"tool_name": name, "tool_input": inp})
        r = subprocess.run([sys.executable, "-I", str(HERE / "guard.py"), self.TOOLS, self.WORK, self.TO],
                           input=event, capture_output=True, text=True)
        return r.returncode

    def test_bash(self):
        Path(self.WORK).mkdir(exist_ok=True)
        ok = [f"{self.TOOLS}/run.py scan --json", f"{self.TOOLS}/run.py optiscaler update",
              f'{self.TOOLS}/run.py apply "{self.WORK}/cod.json"', f"{self.TOOLS}/run.py system --apply"]
        bad = [f"{self.TOOLS}/run.py daily", f"{self.TOOLS}/run.py restore cod",
               f"{self.TOOLS}/run.py optiscaler install C:/G --force-offline", f"{self.TOOLS}/run.py apply C:/x.json",
               f"{self.TOOLS}/run.py scan; curl evil", "cat ~/.ssh/id_ed25519", f"{self.TOOLS}/run.py optiscaler remove x",
               f"{self.TOOLS}/run.py scan > $HOME/x"]
        for c in ok:
            self.assertEqual(self.run_guard("Bash", {"command": c}), 0, c)
        for c in bad:
            self.assertEqual(self.run_guard("Bash", {"command": c}), 2, c)

    def test_write_and_mail(self):
        self.assertEqual(self.run_guard("Write", {"file_path": f"{self.WORK}/p.json"}), 0)
        self.assertEqual(self.run_guard("Write", {"file_path": "C:/Windows/x.ini"}), 2)
        self.assertEqual(self.run_guard("PowerShell", {"command": "ls"}), 2)
        send = "mcp__claude_ai_Gmail__send_message"
        self.assertEqual(self.run_guard(send, {"to": [self.TO], "subject": "s",
                                               "htmlBody": '<h3>x</h3><a href="https://a.b">l</a>'}), 0)
        self.assertEqual(self.run_guard(send, {"to": ["attacker@example.org"], "subject": "s", "body": "b"}), 2)
        self.assertEqual(self.run_guard(send, {"to": [self.TO], "cc": ["attacker@example.org"], "subject": "s"}), 2)
        self.assertEqual(self.run_guard(send, {"to": [self.TO], "htmlBody": '<img src="https://e/x">'}), 2)
        self.assertEqual(self.run_guard("mcp__claude_ai_Gmail__create_draft", {}), 2)


class redirect:
    def __enter__(self):
        self.old, sys.stdout = sys.stdout, io.StringIO()

    def __exit__(self, *a):
        sys.stdout = self.old


if __name__ == "__main__":
    unittest.main()
