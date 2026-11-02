"""Tests for emulators: config editing (INI/TOML/YAML), Eden profiles.dat, Xenia patch toggles, PARAM.SFO,
save links and ROM command lines. No network, no emulator runs."""
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import emulators  # noqa: E402

FABLE = '''title_name = "Fable II" # GOTY
title_id = "4D5307F1"

[[patch]]
    name = "60 FPS"
    author = "someone"
    is_enabled = false

    [[patch.be8]]
        address = 0x82b9c8eb
        value = 0x01

[[patch]]
    name = "21:9 Widescreen"
    is_enabled = false

[[patch]]
    name = "1280x720 Resolution"
    desc = "Original resolution is 1120x720."
    is_enabled = false
'''


def sfo_bytes(fields):
    """Minimal PARAM.SFO with UTF-8 string entries."""
    keys = b"".join(k.encode() + b"\0" for k in fields)
    vals, index, ko, do = b"", b"", 0, 0
    for k, v in fields.items():
        data = v.encode() + b"\0"
        index += struct.pack("<HHIII", ko, 0x0204, len(data), len(data), do)
        ko += len(k) + 1
        vals += data
        do += len(data)
    kt = 20 + len(index)
    dt = kt + len(keys)
    return struct.pack("<4sIIII", b"\0PSF", 0x101, kt, dt, len(fields)) + index + keys + vals


class ConfigEdits(unittest.TestCase):
    def test_ini_sets_existing_and_adds_missing(self):
        text = "[Renderer]\nbackend=1\nresolution_setup=3\n\n[UI]\nfoo=bar\n"
        out = emulators.set_ini(text, "Renderer", {"resolution_setup": "5", "resolution_setup\\default": "false"})
        self.assertIn("resolution_setup=5", out)
        self.assertIn("resolution_setup\\default=false", out)
        self.assertLess(out.index("resolution_setup\\default"), out.index("[UI]"))
        self.assertIn("foo=bar", out)
        self.assertIn("[System]\nuse_docked_mode=1", emulators.set_ini(out, "System", {"use_docked_mode": "1"}))

    def test_game_dir_is_added_once_after_eden_defaults(self):
        out = emulators.add_game_dir("", "D:/Emulation/roms/switch")
        self.assertEqual(emulators.ini_get(out, "UI", "Paths\\gamedirs\\1\\path"), "SDMC")
        self.assertEqual(emulators.ini_get(out, "UI", "Paths\\gamedirs\\4\\path"), "D:/Emulation/roms/switch")
        self.assertEqual(emulators.ini_get(out, "UI", "Paths\\gamedirs\\size"), "4")
        self.assertEqual(emulators.add_game_dir(out, "D:/Emulation/roms/switch"), out)

    def test_toml_keeps_comments_and_escapes_paths(self):
        text = "[GPU]\ndraw_resolution_scale_x = 1  # Scale\nvsync = false\n"
        out = emulators.set_toml(text, "GPU", {"draw_resolution_scale_x": 2, "vsync": True})
        self.assertIn("draw_resolution_scale_x = 2  # Scale", out)
        self.assertIn("vsync = true", out)
        out = emulators.set_toml(out, "Storage", {"content_root": "D:\\Emulation\\saves\\xbox360"})
        self.assertIn('content_root = "D:\\\\Emulation\\\\saves\\\\xbox360"', out)

    def test_yaml_two_level(self):
        text = "Core:\n  PPU Decoder: LLVM\nVideo:\n  Renderer: Vulkan\n  Resolution Scale: 100\nAudio:\n  Volume: 100\n"
        out = emulators.set_yaml(text, {"Video": {"Resolution Scale": "200", "Anisotropic Filter Override": "16"},
                                        "Miscellaneous": {"Exit RPCS3 when process finishes": "true"}})
        self.assertIn("  Resolution Scale: 200\n  Anisotropic Filter Override: 16\nAudio:", out)
        self.assertIn("Miscellaneous:\n  Exit RPCS3 when process finishes: true", out)
        self.assertIn("  PPU Decoder: LLVM", out)


class EdenProfile(unittest.TestCase):
    UUID = "0123456789ABCDEFFEDCBA9876543210"

    def test_new_file_holds_the_save_owner_in_slot_0(self):
        data, slot, changed = emulators.profiles_dat(None, self.UUID, "Player")
        self.assertEqual((len(data), slot, changed), (0x650, 0, True))
        lo, hi = struct.unpack_from("<QQ", data, 0x10)
        self.assertEqual(f"{hi:016X}{lo:016X}", self.UUID)  # how Eden names the save folder
        self.assertEqual(data[0x10 + 0x28:0x10 + 0x2E], b"Player")

    def test_existing_users_are_kept_and_rerun_is_noop(self):
        other, _, _ = emulators.profiles_dat(None, "0" * 31 + "1", "Eden")
        data, slot, changed = emulators.profiles_dat(other, self.UUID, "Player")
        self.assertEqual((slot, changed), (1, True))
        self.assertEqual(data[0x10:0x10 + 0xC8], other[0x10:0x10 + 0xC8])
        self.assertEqual(emulators.profiles_dat(data, self.UUID, "Player")[1:], (1, False))

    def test_profiles_from_save_folders(self):
        with tempfile.TemporaryDirectory() as t:
            base = Path(t) / "0000000000000000"
            for d in ("0" * 32, self.UUID, "JKSV"):
                (base / d).mkdir(parents=True)
            self.assertEqual(emulators.switch_profiles(t), [self.UUID])


class Patches(unittest.TestCase):
    def test_only_wanted_xenia_patches_turn_on(self):
        out = emulators.enable_xenia_patches(FABLE, r"60 FPS|1280x720 Resolution")
        blocks = out.split("[[patch]]")
        self.assertIn("is_enabled = true", blocks[1])
        self.assertIn("is_enabled = false", blocks[2])  # widescreen untouched
        self.assertIn("is_enabled = true", blocks[3])
        self.assertTrue(out.startswith('title_name = "Fable II"'))

    def test_param_sfo(self):
        with tempfile.TemporaryDirectory() as t:
            sfo = Path(t) / "Some Collection" / "PS3_GAME" / "PARAM.SFO"
            sfo.parent.mkdir(parents=True)
            sfo.write_bytes(sfo_bytes({"APP_VER": "01.00", "TITLE": "Some Collection", "TITLE_ID": "BCES00000"}))
            games = emulators.ps3_games(t)
            self.assertEqual(list(games), ["BCES00000"])
            self.assertEqual(games["BCES00000"][1]["TITLE"], "Some Collection")


class Controllers(unittest.TestCase):
    def test_guid_matches_sdl_for_an_xinput_pad(self):
        # SDL 2.32 reported this GUID (name CRC zeroed) for an Xbox Series pad (045e:0b12, version 0) via XInput
        self.assertEqual(emulators.sdl_xinput_guid(0x045E, 0x0B12, 0), "030000005e040000120b000000007801")
        self.assertEqual(emulators.VIRTUAL_X360, "030000005e0400008e02000014017801")

    def test_eden_pro_controller_is_positional_and_flagged(self):
        guid = "030000005e040000120b000000007801"
        v = emulators.eden_pro_controller(guid)
        self.assertEqual(v["player_0_button_a"], f'"engine:sdl,port:0,guid:{guid},button:1"')  # right button
        self.assertEqual(v["player_0_button_b"], f'"engine:sdl,port:0,guid:{guid},button:0"')  # bottom button
        self.assertIn("hat:0,direction:up", v["player_0_button_dup"])
        self.assertIn("axis:5,threshold:0.5", v["player_0_button_zr"])
        self.assertIn("axis_x:3,axis_y:4", v["player_0_rstick"])
        self.assertEqual(v["player_0_type"], "0")  # Pro Controller
        self.assertTrue(all(v[k + "\\default"] == "false" for k in v if not k.endswith("\\default")))

    def test_rebind_rules(self):
        desk, other = "1" * 32, "2" * 32
        self.assertTrue(emulators.needs_pad_binding("", desk))
        self.assertFalse(emulators.needs_pad_binding(f'player_0_button_a="engine:sdl,guid:{desk},button:1"', desk))
        self.assertTrue(emulators.needs_pad_binding(f'player_0_button_a="engine:sdl,guid:{other},button:1"', desk))
        self.assertFalse(emulators.needs_pad_binding('player_0_button_a="engine:keyboard,code:67"', desk))

    def test_rpcs3_player_1_on_xinput(self):
        text = emulators.rpcs3_input()
        # quoted: unquoted, YAML reads "#1" as a comment and RPCS3 finds no device 'XInput Pad'
        self.assertTrue(text.startswith('Player 1 Input:\n  Handler: XInput\n  Device: "XInput Pad #1"\n'))
        self.assertIn("    Cross: A\n", text)
        self.assertIn("    Circle: B\n", text)


class Layout(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.p = emulators.Paths({"EMULATION_ROOT": str(root / "Emulation"), "EMU_DIR": str(root / "Emulators")})

    def tearDown(self):
        self.tmp.cleanup()

    def test_command_per_system(self):
        sw = self.p.roms / "switch" / "Game [0100000000010000].nsp"
        ps3 = self.p.roms / "ps3" / "Some Collection"
        x360 = self.p.roms / "xbox360" / "Game.iso"
        for f in (sw, x360):
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"")
        ps3.mkdir(parents=True)
        exe, a = emulators.command(self.p, sw)
        self.assertEqual((exe.name, a), ("eden.exe", f'-f -g "{sw}"'))
        exe, a = emulators.command(self.p, ps3)
        self.assertEqual(exe.name, "rpcs3.exe")
        self.assertEqual(a, f'--no-gui "{ps3 / "PS3_GAME" / "USRDIR" / "EBOOT.BIN"}"')
        self.assertEqual(emulators.command(self.p, x360)[1], f'"{x360}"')

    def test_link_moves_nothing_and_refuses_existing_data(self):
        target = self.p.saves / "ps3"
        link = Path(self.tmp.name) / "rpcs3" / "savedata"
        link.mkdir(parents=True)
        (link / "SAVE").write_text("x", encoding="utf-8")
        self.assertIn("already holds data", emulators.link_dir(link, target))
        self.assertTrue((link / "SAVE").is_file())
        (link / "SAVE").unlink()
        try:
            self.assertIsNone(emulators.link_dir(link, target))
        except OSError as e:  # symlinks need Developer Mode on Windows CI / unprivileged runners
            self.skipTest(f"no link privilege: {e}")
        (target / "BCES00000").mkdir()
        self.assertTrue((link / "BCES00000").is_dir())
        self.assertIsNone(emulators.link_dir(link, target))  # re-run is a no-op
        self.assertTrue(emulators.is_link(link))


if __name__ == "__main__":
    unittest.main()
