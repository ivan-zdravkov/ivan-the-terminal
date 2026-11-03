"""The runner, the prompt, the allowlist and the guard must agree on every tool the headless run may call."""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
T = HERE.as_posix()
spec = importlib.util.spec_from_file_location("daily_coach_run", HERE / "run.py")
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)
PROMPT = (HERE.parent / "references/prompt.md").read_text(encoding="utf-8")
ME = "me@example.com"


class Agreement(unittest.TestCase):
    def test_every_prompt_tool_exists_is_allowed_and_passes_the_guard(self):
        work = Path("/w")
        _, allowed = run.command("m", "/s.json", work)
        guard = run.settings_for(work, ME, ["example.org"])["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertTrue(guard.endswith(f" {ME} example.org"))
        self.assertNotIn("pythonw", guard)  # pythonw has no stdio: the guard could not read its event
        calls = set(re.findall(r"`\{\{TOOLS\}\}/([\w.]+ [\w-]+)", PROMPT))
        self.assertEqual({"coach.py checks-set", "coach.py context", "coach.py plan-set", "coach.py email"}, calls)
        for call in calls:
            self.assertTrue((HERE / call.split()[0]).is_file(), call)
            self.assertIn(f"Bash({T}/{call}:*)", allowed)
            event = json.dumps({"tool_name": "Bash", "tool_input": {"command": f"{T}/{call}"}})
            p = subprocess.run([sys.executable, "-I", str(HERE / "guard.py"), T, str(work), ME], input=event,
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, f"{call}: {p.stderr}")

    def test_no_interpreter_import_or_mail_tools_beyond_read_and_send(self):
        cmd, allowed = run.command("m", "/s.json", Path("/w"))
        for a in allowed:
            self.assertNotRegex(a, r"Bash\((python|curl|jq|grep|sh|bash|echo|cat)\b|coach\.py (import|ingest|ready)")
            self.assertNotRegex(a, r"__(create_draft|reply|forward|\w*label\w*|trash_\w+)$")
            if a.startswith("mcp__"):
                self.assertRegex(a, r"^mcp__claude_ai_Gmail__(search_threads|get_thread|get_message|send_message)$")
        for t in ("PowerShell", "Monitor", "mcp__claude_ai_Gmail__create_draft"):
            self.assertIn(t, cmd[cmd.index("--disallowedTools"):])

    def test_rule_paths_and_schedule(self):
        self.assertEqual("//c/Work/coach", run.rule_path(Path("C:/Work/coach")))
        self.assertEqual("//srv/work", run.rule_path(Path("/srv/work")))
        self.assertTrue(run.past("10:30", datetime(2026, 1, 1, 10, 30)))
        self.assertFalse(run.past("10:30", datetime(2026, 1, 1, 10, 29)))


class Runner(unittest.TestCase):
    def env(self, tmp, config=f'MODEL="test-model"\nMAIL_TO="{ME}"\nWEB_DOMAINS="a.example b.example"\n'):
        conf = tmp / "config/ivan-the-terminal/daily-coach"
        conf.mkdir(parents=True)
        (conf / "config.env").write_text(config, encoding="utf-8")
        (conf / "profile.md").write_text("Someone.\n", encoding="utf-8")
        env = {**os.environ, "XDG_CONFIG_HOME": str(tmp / "config"), "XDG_STATE_HOME": str(tmp / "state"),
               "XDG_DATA_HOME": str(tmp / "data"), "DAILY_COACH_CONF": str(conf / "config.env"),
               "DAILY_COACH_DATA": str(tmp / "data")}
        return env

    def run_py(self, env, *args):
        return subprocess.run([sys.executable, "-I", str(HERE / "run.py"), *args], env=env, capture_output=True,
                              text=True, encoding="utf-8")

    def test_dry_run_in_a_sandbox(self):
        p = self.run_py(self.env(Path(tempfile.mkdtemp())), "--dry-run")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(" 0 unfilled placeholders", p.stdout)
        self.assertIn("model: test-model", p.stdout)
        self.assertIn(f"mail to: {ME}", p.stdout)
        self.assertRegex(p.stdout, r"guard: .*guard\.py'? .* me@example\.com a\.example b\.example")

    def test_missing_recipient_fails(self):
        p = self.run_py(self.env(Path(tempfile.mkdtemp()), 'MODEL="m"\n'), "--dry-run")
        self.assertEqual(p.returncode, 2)
        self.assertIn("MAIL_TO", p.stderr)

    def test_second_run_waits_for_the_lock(self):
        tmp = Path(tempfile.mkdtemp())
        env = self.env(tmp)
        state = tmp / "state/ivan-the-terminal/daily-coach"
        state.mkdir(parents=True)
        held = run.lock(state / "lock")
        self.addCleanup(held.close)
        p = self.run_py(env, "--import")
        self.assertEqual(p.returncode, 0)
        self.assertIn("already in progress", p.stdout)


if __name__ == "__main__":
    unittest.main()
