import unittest
from unittest import mock

import tvctl

PAGE = """
<a href="https://dl.strem.io/android/v1.10.0-rc.18-androidTV/com.stremio.one-1.10.0-rc.18-21048593-armeabi-v7a.apk">
<a href="https://dl.strem.io/android/v1.9.12-androidTV/com.stremio.one-1.9.12-31048570-armeabi-v7a.apk">
<a href="https://dl.strem.io/android/v1.10.4-androidTV/com.stremio.one-1.10.4-31048580-armeabi-v7a.apk">
<a href="https://dl.strem.io/android/v1.10.4-androidTV/com.stremio.one-1.10.4-33145732-arm64-v8a.apk">
<a href="https://dl.strem.io/android/v2.3.2-android/com.stremio.one-2.3.2-3048580-armeabi-v7a.apk">
"""


class Versions(unittest.TestCase):
    def test_vtuple(self):
        self.assertEqual(tvctl.vtuple("1.104.2-tc3430f0d2-gb01fa89d5"), (1, 104, 2))
        self.assertEqual(tvctl.vtuple("32.68s"), (32, 68))
        self.assertEqual(tvctl.vtuple(None), ())
        self.assertGreater(tvctl.vtuple("1.10.4"), tvctl.vtuple("1.9.12"))


class Sources(unittest.TestCase):
    def test_stremio_picks_newest_stable_tv_build_for_abi(self):
        ver, url, sha = tvctl.stremio_page_latest(PAGE, ["arm64-v8a", "armeabi-v7a"])
        self.assertEqual((ver, sha), ("1.10.4", None))
        self.assertTrue(url.endswith("1.10.4-33145732-arm64-v8a.apk"))
        ver, url, _ = tvctl.stremio_page_latest(PAGE, ["armeabi-v7a"])
        self.assertTrue(url.endswith("1.10.4-31048580-armeabi-v7a.apk"))

    def test_stremio_ignores_phone_builds(self):
        with self.assertRaises(LookupError):
            tvctl.stremio_page_latest(PAGE, ["x86"])

    def test_smarttube_matches_abi_and_digest(self):
        rel = {"tag_name": "32.68s", "assets": [
            {"name": "SmartTube_stable_32.68_universal.apk", "browser_download_url": "u", "digest": "sha256:aa"},
            {"name": "SmartTube_stable_32.68_armeabi-v7a.apk", "browser_download_url": "v7", "digest": "sha256:bb"},
        ]}
        with mock.patch.object(tvctl, "http", return_value=rel):
            self.assertEqual(tvctl.smarttube(["armeabi-v7a", "armeabi"]), ("32.68", "v7", "bb"))
            self.assertEqual(tvctl.smarttube(["x86"]), ("32.68", "u", "aa"))

    def test_keymapper_foss_asset_and_digest(self):
        rel = {"tag_name": "v4.6.2", "assets": [
            {"name": "keymapper-4.6.2.apk", "browser_download_url": "play", "digest": "sha256:aa"},
            {"name": "keymapper-4.6.2-foss.apk", "browser_download_url": "foss", "digest": "sha256:bb"},
        ]}
        with mock.patch.object(tvctl, "http", return_value=rel):
            self.assertEqual(tvctl.keymapper(["armeabi-v7a"]), ("4.6.2", "foss", "bb"))


class FakeTV:
    def __init__(self, replies):
        self.replies, self.ran = replies, None

    def sh(self, cmd):
        return next((v for k, v in self.replies.items() if cmd.startswith(k)), "")

    def adb(self, *args, timeout=60, input=None):
        self.ran = input


class Bridge(unittest.TestCase):
    START = 'echo hi\n$STARTER_PATH --apk="/data/app/~~old/km-old/base.apk" --lib="/data/app/~~old/km-old/lib/arm" ' \
            '--package="io.github.sds100.keymapper" --version="288"\n'

    def test_start_uses_current_install_paths(self):
        tv = FakeTV({"cat ": self.START, "pm path": "package:/data/app/~~new/km-new/base.apk",
                     "ls -d": "/data/app/~~new/km-new/lib/arm", "dumpsys package": "versionCode=301 minSdk=21"})
        with mock.patch.object(tvctl.time, "sleep"):
            self.assertIsNone(tvctl.start_bridge(tv))
        self.assertIn('--apk="/data/app/~~new/km-new/base.apk" --lib="/data/app/~~new/km-new/lib/arm"', tv.ran)
        self.assertIn('--version="301"', tv.ran)

    def test_missing_start_script_is_reported(self):
        tv = FakeTV({"pm path": "package:/data/app/x/base.apk"})
        self.assertIn("start.sh missing", tvctl.start_bridge(tv))
        self.assertIsNone(tv.ran)


if __name__ == "__main__":
    unittest.main()
