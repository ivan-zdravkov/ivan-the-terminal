import importlib.util
import os
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
TMP = tempfile.mkdtemp()
with mock.patch.dict(os.environ, DAILY_COACH_CONF=str(Path(TMP, "config.env")), DAILY_COACH_DATA=TMP):
    # only while importing: test_coach's guard subprocesses (same process under discover) read these too
    spec = importlib.util.spec_from_file_location("shortcut", HERE / "shortcut.py")
    shortcut = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shortcut)

CFG = {"HEALTH_DIR": "health", "RING_APP": "com.example.ring", "RING_APP_NAME": "Ring", "HEALTH_TYPES": ""}


def refs(node):
    """Every OutputUUID an action parameter points at."""
    if isinstance(node, dict):
        if "OutputUUID" in node:
            yield node["OutputUUID"]
        for v in node.values():
            yield from refs(v)
    elif isinstance(node, list):
        for v in node:
            yield from refs(v)


class ShortcutTest(unittest.TestCase):
    def build(self, **cfg):
        wf = shortcut.build({**CFG, **cfg}, "owner/private-repo")
        plistlib.loads(plistlib.dumps(wf, fmt=plistlib.FMT_XML))  # serializable
        return wf, [(a["WFWorkflowActionIdentifier"].rsplit(".", 1)[-1] if "repeat" not in a["WFWorkflowActionIdentifier"]
                     else "repeat", a["WFWorkflowActionParameters"]) for a in wf["WFWorkflowActions"]]

    def test_structure(self):
        wf, acts = self.build()
        uuids = [p["UUID"] for _, p in acts if "UUID" in p]
        self.assertEqual(len(uuids), len(set(uuids)))
        for _, p in acts:  # every variable points at an earlier action
            for r in refs(p):
                self.assertIn(r, uuids)
        groups = {}
        for _, p in acts:  # every If and Repeat is opened and closed once
            if "GroupingIdentifier" in p:
                groups.setdefault(p["GroupingIdentifier"], []).append(p["WFControlFlowMode"])
        self.assertTrue(groups and all(modes == [0, 2] for modes in groups.values()), groups)
        found = [p["WFContentItemFilter"]["Value"]["WFActionParameterFilterTemplates"][0]["Values"]["Enumeration"]["Value"]
                 for i, p in acts if i == "quantity"]
        self.assertEqual(found, [t.strip() for t in shortcut.DEFAULT_TYPES.split(",")])
        self.assertEqual(wf["WFWorkflowName"], "Health sync")

    def test_token_only_on_import(self):
        wf, acts = self.build()
        (q,) = wf["WFWorkflowImportQuestions"]
        ident, params = acts[q["ActionIndex"]]
        self.assertEqual((ident, q["ParameterKey"], params["WFTextActionText"]), ("gettext", "WFTextActionText", ""))
        put = next(p for i, p in acts if i == "downloadurl")
        self.assertEqual(put["WFHTTPMethod"], "PUT")
        self.assertTrue(put["WFURL"]["Value"]["string"].startswith(
            "https://api.github.com/repos/owner/private-repo/contents/health/"))
        auth = put["WFHTTPHeaders"]["Value"]["WFDictionaryFieldValueItems"][0]["WFValue"]["Value"]
        self.assertEqual(list(auth["attachmentsByRange"].values())[0]["OutputUUID"], params["UUID"])

    def test_ring_app_optional(self):
        _, acts = self.build()
        self.assertEqual(next(p for i, p in acts if i == "openapp")["WFSelectedApp"]["BundleIdentifier"],
                         "com.example.ring")
        _, acts = self.build(RING_APP="")
        self.assertNotIn("openapp", [i for i, _ in acts])

    def test_bad_config(self):
        with self.assertRaises(ValueError):
            self.build(HEALTH_TYPES="Sleep, Mood")
        with self.assertRaises(ValueError):
            shortcut.build(CFG, "owner/repo/../x")

    def test_repo_slug(self):
        for url in ("git@github.com:owner/repo.git", "https://github.com/owner/repo", "ssh://git@github.com/owner/repo.git"):
            with mock.patch.object(shortcut.subprocess, "run", return_value=mock.Mock(stdout=url + "\n")):
                self.assertEqual(shortcut.repo_slug("."), "owner/repo")
        with mock.patch.object(shortcut.subprocess, "run", return_value=mock.Mock(stdout="https://example.org/x.git")):
            with self.assertRaises(ValueError):
                shortcut.repo_slug(".")

    def test_sign_checks_the_answer(self):
        xml, signed = Path(TMP, "s.xml"), Path(TMP, "s.shortcut")
        xml.write_text("<plist/>", encoding="utf-8")
        def curl(stdout, code=0):
            return mock.patch.object(shortcut.subprocess, "run",
                                     return_value=mock.Mock(stdout=stdout, stderr=b"", returncode=code))
        with curl(b"<html>home page</html>"), self.assertRaises(ValueError):
            shortcut.sign(xml, signed)
        with curl(b"AEA1partial", code=28), self.assertRaises(ValueError):  # timed out
            shortcut.sign(xml, signed)
        self.assertFalse(signed.exists())
        with curl(b"AEA1signed") as run:
            self.assertEqual(shortcut.sign(xml, signed), 10)
        self.assertEqual(signed.read_bytes(), b"AEA1signed")
        argv = run.call_args.args[0]
        self.assertEqual((argv[0], argv[-1]), ("curl", shortcut.HUBSIGN))
        self.assertIn("shortcutName=Healthsync", argv)  # the service fails on a space


if __name__ == "__main__":
    unittest.main()
