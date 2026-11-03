"""The runner, the prompt, the allowlist and the guard must agree on every tool the headless run may call."""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
T = HERE.as_posix()
spec = importlib.util.spec_from_file_location("job_digest_run", HERE / "run.py")
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)
PROMPT = (HERE.parent / "references/prompt.md").read_text(encoding="utf-8")
ME = "me@example.com"


class Agreement(unittest.TestCase):
    def test_every_prompt_tool_exists_is_allowed_and_passes_the_guard(self):
        work = Path("/w")
        _, allowed = run.command("m", "/s.json", work)
        guard = run.settings_for(work, ME)["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertIn(f"{T}/guard.py", guard)
        self.assertTrue(guard.endswith(ME))
        calls = set(re.findall(r"`\{\{TOOLS\}\}/([\w.]+)", PROMPT))
        self.assertEqual({"fetch.py", "q.py", "page.py"}, calls)
        for name in calls:
            self.assertTrue((HERE / name).is_file(), name)
            self.assertIn(f"Bash({T}/{name}:*)", allowed)
            event = json.dumps({"tool_name": "Bash", "tool_input": {"command": f"{T}/{name} x"}})
            p = subprocess.run([sys.executable, "-I", str(HERE / "guard.py"), T, str(work), ME], input=event,
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, f"{name}: {p.stderr}")

    def test_no_interpreter_and_only_the_digest_send_is_allowed(self):
        cmd, allowed = run.command("m", "/s.json", Path("/w"))
        for a in allowed:
            self.assertNotRegex(a, r"Bash\((python|curl|jq|grep|sh|bash|echo|cat)\b")
            self.assertNotRegex(a, r"__(reply|forward|update_draft|trash_\w+|mark_\w+_spam)$")
        self.assertIn("PowerShell", cmd[cmd.index("--disallowedTools"):])
        self.assertIn("{{DIGEST_TO}}", PROMPT)
        self.assertIn("{{WORK}}", PROMPT)

    def test_rule_paths(self):
        self.assertEqual("//c/Work/digest", run.rule_path(Path("C:/Work/digest")))
        self.assertEqual("//srv/work", run.rule_path(Path("/srv/work")))

    def test_prompt_archives_only_linkedin_and_spares_security_mail(self):
        self.assertIn("-from:security-noreply@linkedin.com", PROMPT)
        self.assertIn("-is:starred", PROMPT)
        self.assertNotIn("jobs.py", PROMPT)


class DryRun(unittest.TestCase):
    def sandbox(self, config):
        tmp = Path(tempfile.mkdtemp())
        conf = tmp / "config/ivan-the-terminal/job-digest"
        conf.mkdir(parents=True)
        (conf / "config.env").write_text(config, encoding="utf-8")
        (conf / "profile.md").write_text("A candidate.\n", encoding="utf-8")
        env = {**os.environ, "XDG_CONFIG_HOME": str(tmp / "config"), "XDG_STATE_HOME": str(tmp / "state")}
        p = subprocess.run([sys.executable, "-I", str(HERE / "run.py"), "--dry-run"], env=env, capture_output=True,
                           text=True, encoding="utf-8")
        return tmp, p

    def test_dry_run_in_a_sandbox(self):
        tmp, p = self.sandbox(f'MODEL="test-model"\nDIGEST_TO="{ME}"\n')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(" 0 unfilled placeholders", p.stdout)
        self.assertIn("model: test-model", p.stdout)
        self.assertIn(f"digest to: {ME}", p.stdout)
        self.assertIn("run at: 16:15", p.stdout)
        self.assertIn("fetch.py", p.stdout)
        settings = json.loads((tmp / "state/ivan-the-terminal/job-digest/settings.json").read_text(encoding="utf-8"))
        self.assertIn("guard.py", settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"])

    def test_missing_recipient_fails(self):
        _, p = self.sandbox('MODEL="test-model"\n')
        self.assertEqual(p.returncode, 2)
        self.assertIn("DIGEST_TO", p.stderr)

    def test_unconfigured_is_a_no_op(self):
        tmp = tempfile.mkdtemp()
        p = subprocess.run([sys.executable, "-I", str(HERE / "run.py")], capture_output=True, text=True,
                           env={**os.environ, "XDG_CONFIG_HOME": tmp, "XDG_STATE_HOME": tmp})
        self.assertEqual(p.returncode, 0)
        self.assertIn("not configured", p.stdout)


if __name__ == "__main__":
    unittest.main()
