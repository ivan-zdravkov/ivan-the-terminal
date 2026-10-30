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
spec = importlib.util.spec_from_file_location("job_digest_run", HERE / "run.py")
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)
PROMPT = (HERE.parent / "references/prompt.md").read_text(encoding="utf-8")


@unittest.skipIf(os.name == "nt", "guards the Bash tool with POSIX paths; Windows headless runs are on the roadmap")
class Agreement(unittest.TestCase):
    def test_every_prompt_tool_exists_is_allowed_and_passes_the_guard(self):
        work = Path("/w")
        _, allowed = run.command("m", "/s.json", work)
        guard = run.settings_for(work)["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertIn(str(HERE / "guard.py"), guard)
        calls = set(re.findall(r"`\{\{TOOLS\}\}/([\w.]+(?: [\w-]+)?)", PROMPT))
        self.assertTrue(calls)
        for call in calls:
            name = call.split()[0]
            self.assertTrue((HERE / name).is_file(), name)
            self.assertTrue(any(a == f"Bash({HERE}/{call}:*)" or a == f"Bash({HERE}/{name}:*)" for a in allowed), call)
            event = json.dumps({"tool_name": "Bash", "tool_input": {"command": f"{HERE}/{call} x"}})
            p = subprocess.run([sys.executable, "-I", str(HERE / "guard.py"), str(HERE), str(work)], input=event,
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, f"{call}: {p.stderr}")

    def test_no_interpreter_or_send_tool_is_allowed(self):
        _, allowed = run.command("m", "/s.json", Path("/w"))
        for a in allowed:
            self.assertNotRegex(a, r"Bash\((python|curl|jq|grep|sh|bash)\b")
            self.assertNotRegex(a, r"__(send_message|reply|forward|update_draft)$")
            self.assertNotRegex(a, r"jobs\.py (serve|notify)")


class DryRun(unittest.TestCase):
    def test_dry_run_in_a_sandbox(self):
        tmp = Path(tempfile.mkdtemp())
        conf = tmp / "config/ivan-the-terminal/job-digest"
        conf.mkdir(parents=True)
        (conf / "config.env").write_text('MODEL="test-model"\nTOKEN="t0k"\nPORT=0\n', encoding="utf-8")
        (conf / "profile.md").write_text("A candidate.\n", encoding="utf-8")
        env = {**os.environ, "XDG_CONFIG_HOME": str(tmp / "config"), "XDG_STATE_HOME": str(tmp / "state"),
               "XDG_DATA_HOME": str(tmp / "data")}
        env.pop("JOB_DIGEST_CONF", None), env.pop("JOB_DIGEST_DATA", None)
        p = subprocess.run([sys.executable, "-I", str(HERE / "run.py"), "--dry-run"], env=env, capture_output=True,
                           text=True, encoding="utf-8")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(" 0 unfilled placeholders", p.stdout)
        self.assertIn("model: test-model", p.stdout)
        self.assertIn("fetch.py", p.stdout)
        settings = json.loads((tmp / "state/ivan-the-terminal/job-digest/settings.json").read_text(encoding="utf-8"))
        self.assertIn("guard.py", settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"])

    def test_unconfigured_is_a_no_op(self):
        tmp = tempfile.mkdtemp()
        p = subprocess.run([sys.executable, "-I", str(HERE / "run.py")], capture_output=True, text=True,
                           env={**os.environ, "XDG_CONFIG_HOME": tmp, "XDG_STATE_HOME": tmp})
        self.assertEqual(p.returncode, 0)
        self.assertIn("not configured", p.stdout)


if __name__ == "__main__":
    unittest.main()
