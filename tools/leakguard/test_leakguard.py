"""Tests for leakguard. Samples are assembled at runtime so this file stays clean under its own scan."""
import hashlib
import io
import json
import os
import subprocess
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

    def test_bank_details(self):
        self.assertIn("payment-card", rules_hit(J(["4111 ", "1111 1111 1111"])))
        self.assertNotIn("payment-card", rules_hit(J(["4111 ", "1111 1111 1112"])))
        self.assertIn("bank-account", rules_hit("IBAN: " + J(["BG80", "BNBG96611020345678"])))
        self.assertEqual(set(), rules_hit("IBANs and account numbers are blocked, a BIC with an account too"))

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


class GitBypasses(unittest.TestCase):
    """Regression tests for bypasses found in the first security review."""
    NAME = J(["Johnny ", "Placeholder"])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.com"],
                     ["config", "user.name", "t"], ["config", "core.hooksPath", "/dev/null"]):
            self.git(*args)
        (self.repo / "a.txt").write_text("clean\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")
        self.patches = [mock.patch.object(leakguard, "ROOT", self.repo),
                        mock.patch.dict(os.environ, {"LEAKGUARD_DENYLIST_CONTENT": self.NAME,
                                                     "LEAKGUARD_DENYLIST": "/nonexistent"})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)

    def scan(self, mode, *args):
        with redirect_stderr(io.StringIO()):
            g = leakguard.Guard()
            {"staged": leakguard.cmd_staged, "range": leakguard.cmd_range, "tree": leakguard.cmd_tree}[mode](g, *args)
        return g.findings

    def test_pure_rename_path_is_scanned(self):
        self.git("mv", "a.txt", f"{self.NAME}.md")
        self.assertTrue(self.scan("staged"))
        self.git("commit", "-qm", "rename")
        self.assertTrue(self.scan("range", "HEAD~1", "HEAD"))

    def test_utf16_and_nul_content_is_scanned(self):
        (self.repo / "u16.txt").write_bytes(f"{self.NAME}\n".encode("utf-16"))
        (self.repo / "nul.txt").write_bytes(b"x\0\n" + self.NAME.encode())
        self.git("add", "-A")
        for mode in ("staged", "tree"):
            hit_files = {f.split(":")[0].split(" ")[0] for f in self.scan(mode)}
            self.assertEqual({"u16.txt", "nul.txt"}, hit_files, mode)

    def test_diff_attribute_does_not_hide_content(self):
        (self.repo / ".gitattributes").write_text("*.md -diff\n")
        (self.repo / "notes.md").write_text(f"{self.NAME}\n")
        self.git("add", "-A")
        self.assertTrue(self.scan("staged"))

    def test_content_hidden_in_merge_commit_is_scanned(self):
        self.git("switch", "-qc", "side")
        (self.repo / "b.txt").write_text("side\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "side")
        self.git("switch", "-q", "main")
        self.git("merge", "-q", "--no-commit", "--no-ff", "side")
        (self.repo / "evil.txt").write_text(f"{self.NAME}\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "merge")
        self.git("rm", "-q", "evil.txt")
        self.git("commit", "-qm", "cleanup")
        self.assertTrue(self.scan("range", "HEAD~2", "HEAD"))

    def test_candidates_surface_unknown_proper_nouns(self):
        (self.repo / "doc.md").write_text("We met Zorbalina at the Placeholderton club; the club was fine.\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "doc")
        out = io.StringIO()
        with mock.patch("sys.stdout", out), redirect_stderr(io.StringIO()):
            leakguard.cmd_candidates(leakguard.Guard(), "HEAD~1", "HEAD")
        terms = {line.split("\t")[1] for line in out.getvalue().splitlines()}
        self.assertTrue({"Zorbalina", "Placeholderton"} <= terms)
        self.assertNotIn("club", terms)

    def test_documents_are_rejected(self):
        (self.repo / "cv.pdf").write_bytes(b"%PDF-1.7 clean")
        self.git("add", "-A")
        self.assertIn("document-file", " ".join(self.scan("staged")))


class HookEdges(unittest.TestCase):
    def _hook(self, cmd, cwd):
        payload = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd)}
        with mock.patch("sys.stdin", io.StringIO(json.dumps(payload))), redirect_stderr(io.StringIO()), \
                mock.patch.dict(os.environ, {"LEAKGUARD_DENYLIST_CONTENT": "Bob"}):
            return leakguard.cmd_claude_hook(leakguard.Guard())

    def test_uploaded_files_are_scanned_in_every_form(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d, "b.md")
            f.write_text("hi Bob\n")
            for cmd in (f"gh pr create --body-file={f}", f"gh release create v1 --notes-file {f}",
                        f"gh gist create {f}", f'gh pr create --body "$(cat {f})"'):
                self.assertEqual(2, self._hook(cmd, leakguard.ROOT), cmd)

    def test_hook_bypass_flags_are_blocked(self):
        root = leakguard.ROOT
        self.assertEqual(2, self._hook("git commit --no-verify -m x", root))
        self.assertEqual(2, self._hook("git -C . commit -nm x", root))
        self.assertEqual(0, self._hook("git commit -m 'fine'", root))

    def test_hashed_secret_inside_larger_token(self):
        secret = J(["hunter", "2-xyz"])
        env = {"LEAKGUARD_DENYLIST_CONTENT": "sha256:" + hashlib.sha256(secret.encode()).hexdigest()}
        for text in (f"password:{secret}", f"url?token={secret}&x=1", f"{secret}/backup", f"#{secret}"):
            self.assertIn("denylist#sha256", rules_hit(text, **env), text)


if __name__ == "__main__":
    unittest.main()
