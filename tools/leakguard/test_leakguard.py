"""Tests for leakguard. Samples are assembled at runtime so this file stays clean under its own scan."""
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import leakguard  # noqa: E402

J = "".join


def rules_hit(text, **env):
    with mock.patch.dict(os.environ, {"LEAKGUARD_DENYLIST": "/nonexistent", **env}, clear=False), \
            redirect_stderr(io.StringIO()):
        g = leakguard.Guard()
        g.scan_text("t", text)
    return {f.split(": ")[1] for f in g.findings}


class GenericRules(unittest.TestCase):
    def test_private_and_tailscale_ips(self):
        self.assertIn("ipv4", rules_hit(".".join(["192", "168", "0", "4"])))
        self.assertIn("ipv4", rules_hit(".".join(["100", "101", "7", "9"]) + ":47989"))

    def test_safe_ips_pass(self):
        for ip in ("127.0.0.1", "0.0.0.0", ".".join(["192", "0", "2", "10"]), "999.1.1.1"):
            self.assertNotIn("ipv4", rules_hit(ip), ip)

    def test_version_strings_with_more_parts_pass(self):
        self.assertNotIn("ipv4", rules_hit("version 44.20260928.0.1.2"))

    def test_mac_address(self):
        self.assertIn("mac-address", rules_hit(":".join(["a4", "83", "e7", "11", "22", "33"])))

    def test_emails(self):
        self.assertIn("email", rules_hit(J(["someone", "@", "gmail.com"])))
        self.assertNotIn("email", rules_hit(J(["dev", "@", "example.com"]) + " git@github.com"))

    def test_phones(self):
        self.assertIn("phone", rules_hit(J(["+359", " 88 ", "123 4567"])))
        self.assertIn("phone-bg", rules_hit(J(["088", "7123456"])))
        self.assertEqual(set(), rules_hit("2026-10-22T10:15:00+03:00"))

    def test_home_paths(self):
        self.assertIn("home-path", rules_hit(J(["/var/ho", "me/alice/Games"])))
        self.assertIn("home-path", rules_hit(J(["/run/me", "dia/alice/Backup"])))
        self.assertNotIn("home-path", rules_hit("~/Games $HOME/x /home/user/x /home/linuxbrew/.linuxbrew"))

    def test_tailnet_and_mtp(self):
        self.assertIn("tailnet", rules_hit(J(["box.tail1234", ".ts.net"])))
        self.assertIn("mtp-uri", rules_hit(J(["mtp", "://DEVICE_SERIAL123/disk"])))

    def test_keys(self):
        self.assertIn("private-key", rules_hit(J(["-----BEGIN OPENSSH ", "PRIVATE KEY-----"])))
        self.assertIn("age-secret-key", rules_hit(J(["AGE-SECRET-KEY-1", "Q" * 58])))

    def test_iban_checksum(self):
        self.assertIn("iban", rules_hit(J(["GB82", " WEST 1234 5698 7654 32"])))
        self.assertNotIn("iban", rules_hit(J(["GB00", " WEST 1234 5698 7654 32"])))

    def test_inline_allow(self):
        line = ".".join(["10", "0", "0", "1"]) + "  # leakguard" + ":allow"
        self.assertEqual(set(), rules_hit(line))


class Denylist(unittest.TestCase):
    def test_plain_terms_are_case_insensitive_whole_word_and_span_whitespace(self):
        env = {"LEAKGUARD_DENYLIST_CONTENT": "# comment\nAcme Sports Club\nBob"}
        self.assertTrue(any(r.startswith("denylist") for r in rules_hit("at ACME  sports club", **env)))
        self.assertEqual(set(), rules_hit("Bobsled", **env))

    def test_hashed_tokens(self):
        secret = J(["hunter", "2-xyz"])
        env = {"LEAKGUARD_DENYLIST_CONTENT": "sha256:" + hashlib.sha256(secret.encode()).hexdigest()}
        self.assertIn("denylist#sha256", rules_hit(f"PASSWORD={secret}.", **env))

    def test_inline_allow_cannot_bypass_denylist(self):
        env = {"LEAKGUARD_DENYLIST_CONTENT": "Bob"}
        self.assertIn("denylist#1", rules_hit("Bob leakguard" + ":allow", **env))

    def test_redaction(self):
        with mock.patch.dict(os.environ, {"LEAKGUARD_DENYLIST_CONTENT": "Bob"}), redirect_stderr(io.StringIO()):
            g = leakguard.Guard(redact=True)
            g.scan_text("t", "Bob")
        self.assertEqual(["t:1: denylist#1: [redacted]"], g.findings)


class PatchAndHook(unittest.TestCase):
    def test_patch_scans_added_lines_only(self):
        ip = ".".join(["10", "1", "2", "3"])
        patch = "\n".join(["diff --git a/f b/f", "--- a/f", "+++ b/f", "@@ -1 +7,2 @@",
                           f"-{ip}", "+clean", f"+{ip}"])
        with redirect_stderr(io.StringIO()):
            g = leakguard.Guard()
            g.scan_patch(patch)
        self.assertEqual([f"f:8: ipv4: {ip}"], g.findings)

    def _hook(self, payload):
        with mock.patch("sys.stdin", io.StringIO(json.dumps(payload))), redirect_stderr(io.StringIO()):
            return leakguard.cmd_claude_hook(leakguard.Guard())

    def test_hook_blocks_writes_inside_repo(self):
        ip = ".".join(["10", "1", "2", "3"])
        inside = str(leakguard.ROOT / "docs" / "x.md")
        self.assertEqual(2, self._hook({"tool_name": "Write", "tool_input": {"file_path": inside, "content": ip}}))

    def test_hook_ignores_writes_outside_repo(self):
        with tempfile.TemporaryDirectory() as d:
            payload = {"tool_name": "Write", "tool_input": {"file_path": f"{d}/x", "content": ".".join(["10", "1", "2", "3"])}}
            self.assertEqual(0, self._hook(payload))

    def test_hook_scans_gh_publishing_commands(self):
        ip = ".".join(["10", "1", "2", "3"])
        cmd = {"command": f"gh pr create --title t --body 'host {ip}'"}
        self.assertEqual(2, self._hook({"tool_name": "Bash", "tool_input": cmd, "cwd": str(leakguard.ROOT)}))
        self.assertEqual(0, self._hook({"tool_name": "Bash", "tool_input": {"command": f"ping {ip}"},
                                        "cwd": str(leakguard.ROOT)}))


if __name__ == "__main__":
    unittest.main()
