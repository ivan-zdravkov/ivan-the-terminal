import base64
import importlib.util
import json
import os
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("webapp", HERE / "webapp.py")
webapp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(webapp)


def unb64u(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def raw_to_der(raw):
    def integer(b):
        b = b.lstrip(b"\0") or b"\0"
        b = b"\0" + b if b[0] & 0x80 else b
        return b"\x02" + bytes([len(b)]) + b
    body = integer(raw[:32]) + integer(raw[32:])
    return b"\x30" + bytes([len(body)]) + body


class Icons(unittest.TestCase):
    def test_png_is_valid_and_sized(self):
        png = webapp.icon_png(48, "#2f6f4f", "#ffffff", "ring")
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", png[16:24]), (48, 48))
        idat = png[png.index(b"IDAT") + 4:png.index(b"IEND") - 8]
        self.assertEqual(len(zlib.decompress(idat)), 48 * (1 + 48 * 3))

    def test_static_paths(self):
        self.assertIn("showNotification", webapp.static("sw.js", "#000000", "#ffffff", "case")[0])
        self.assertEqual(webapp.static("icon-180.png", "#000000", "#ffffff", "case")[1], "image/png")
        self.assertIsNone(webapp.static("icon-9999.png", "#000000", "#ffffff", "case"))
        self.assertIsNone(webapp.static("../etc/passwd", "#000000", "#ffffff", "case"))


class PushTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.push = webapp.Push(self.tmp.name, "https://app.example.com")

    def tearDown(self):
        self.tmp.cleanup()

    def test_endpoint_allowlist(self):
        for ok in ("https://web.push.apple.com/abc", "https://fcm.googleapis.com/fcm/send/x",
                   "https://wns2-par02p.notify.windows.com/w/?token=1"):
            self.assertTrue(webapp.valid_endpoint(ok), ok)
        for bad in ("http://web.push.apple.com/a", "https://web.push.apple.com.evil.example/a",
                    "https://127.0.0.1/a", "https://evil.example/web.push.apple.com",
                    "https://u@web.push.apple.com/",  # leakguard:allow (userinfo test, not an address)
                    "https://web.push.apple.com:8443/a", "notify.windows.com", None):
            self.assertFalse(webapp.valid_endpoint(bad), bad)
        with self.assertRaises(ValueError):
            self.push.subscribe({"endpoint": "https://evil.example/x"})

    def test_subscriptions_dedupe_and_cap(self):
        for i in range(15):
            self.push.subscribe({"endpoint": f"https://web.push.apple.com/{i}", "keys": {}})
        self.push.subscribe({"endpoint": "https://web.push.apple.com/14"})
        self.assertEqual(len(self.push.subs()), webapp.MAX_SUBS)
        self.assertEqual(self.push.subs()[-1], "https://web.push.apple.com/14")
        if os.name == "posix":  # Windows has no mode bits; the profile ACL protects it
            self.assertEqual(Path(self.tmp.name, "push.json").stat().st_mode & 0o777, 0o600)

    def test_vapid_jwt_verifies(self):
        key = unb64u(self.push.public_key())
        self.assertEqual((len(key), key[0]), (65, 4))
        if os.name == "posix":  # Windows has no mode bits; the profile ACL protects it
            self.assertEqual(Path(self.tmp.name, "vapid.pem").stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.push.public_key(), webapp.b64u(key))  # stable: the key is made once
        token = self.push.jwt("https://web.push.apple.com/abc")
        h, c, s = token.split(".")
        self.assertEqual(json.loads(unb64u(c))["aud"], "https://web.push.apple.com")
        self.assertEqual(json.loads(unb64u(h))["alg"], "ES256")
        pub, sig = Path(self.tmp.name, "pub.pem"), Path(self.tmp.name, "sig.der")
        pub.write_bytes(subprocess.run(["openssl", "ec", "-in", str(self.push.key), "-pubout"], capture_output=True).stdout)
        sig.write_bytes(raw_to_der(unb64u(s)))
        ok = subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(pub), "-signature", str(sig)],
                            input=f"{h}.{c}".encode(), capture_output=True)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)

    def test_der_to_raw_rejects_garbage(self):
        for bad in (b"", b"\x31\x00", b"\x30\x06\x03\x01\x01\x02\x01\x01"):
            with self.assertRaises((ValueError, IndexError)):
                webapp.der_to_raw(bad)

    def test_send_drops_gone_subscriptions(self):
        for ep in ("https://web.push.apple.com/live", "https://web.push.apple.com/gone"):
            self.push.subscribe({"endpoint": ep})
        seen = []

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake(req, timeout):
            seen.append((req.get_method(), req.data, req.get_header("Authorization"), req.get_header("Ttl")))
            if req.full_url.endswith("gone"):
                raise webapp.urllib.error.HTTPError(req.full_url, 410, "Gone", {}, None)
            return Resp()
        with mock.patch.object(webapp.urllib.request, "urlopen", fake):
            self.assertEqual(self.push.send(), (1, 1))
        self.assertEqual(self.push.subs(), ["https://web.push.apple.com/live"])
        method, data, auth, ttl = seen[0]
        self.assertEqual((method, data, ttl), ("POST", b"", "43200"))
        self.assertRegex(auth, r"^vapid t=[\w-]+\.[\w-]+\.[\w-]+, k=[\w-]{87}$")


class Pages(unittest.TestCase):
    def test_head_and_manifest(self):
        h = webapp.head("Jobs <x>", "#123456", "KEY")
        self.assertIn('content="Jobs &lt;x&gt;"', h)
        self.assertIn('name="vapid" content="KEY"', h)
        m = json.loads(webapp.manifest("Jobs", "#ffffff", "#123456"))
        self.assertEqual((m["display"], m["start_url"]), ("standalone", "./"))
        self.assertTrue(all(not i["src"].startswith("/") for i in m["icons"]))  # relative: works under any prefix


if __name__ == "__main__":
    unittest.main()
