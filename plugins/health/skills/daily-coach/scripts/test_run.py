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
spec = importlib.util.spec_from_file_location("daily_coach_run", HERE / "run.py")
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)
PROMPT = (HERE.parent / "references/prompt.md").read_text(encoding="utf-8")


@unittest.skipIf(os.name == "nt", "guards the Bash tool with POSIX paths; Windows headless runs are on the roadmap")
class Agreement(unittest.TestCase):
    def test_every_prompt_tool_exists_is_allowed_and_passes_the_guard(self):
        work = Path("/w")
        _, allowed = run.command("m", "/s.json", work)
        guard = run.settings_for(work, ["example.org"])["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertTrue(guard.endswith(" example.org"))
        calls = set(re.findall(r"`\{\{TOOLS\}\}/([\w.]+ [\w-]+)", PROMPT))
        self.assertTrue(calls)
        for call in calls:
            self.assertTrue((HERE / call.split()[0]).is_file(), call)
            self.assertIn(f"Bash({HERE}/{call}:*)", allowed)
            event = json.dumps({"tool_name": "Bash", "tool_input": {"command": f"{HERE}/{call}"}})
            p = subprocess.run([sys.executable, "-I", str(HERE / "guard.py"), str(HERE), str(work)], input=event,
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, f"{call}: {p.stderr}")

    def test_no_interpreter_mcp_or_push_is_allowed(self):
        cmd, allowed = run.command("m", "/s.json", Path("/w"))
        for a in allowed:
            self.assertNotRegex(a, r"Bash\((python|curl|jq|grep|sh|bash)\b|^mcp__|coach\.py (serve|notify)")
        self.assertIn("mcp__claude_ai_Gmail", cmd[cmd.index("--disallowedTools"):])


class Runner(unittest.TestCase):
    def env(self, tmp):
        conf = tmp / "config/ivan-the-terminal/daily-coach"
        conf.mkdir(parents=True)
        (conf / "config.env").write_text('MODEL="test-model"\nTOKEN="t0k"\nPORT=0\nWEB_DOMAINS="a.example b.example"\n',
                                         encoding="utf-8")
        (conf / "profile.md").write_text("Someone.\n", encoding="utf-8")
        env = {**os.environ, "XDG_CONFIG_HOME": str(tmp / "config"), "XDG_STATE_HOME": str(tmp / "state"),
               "XDG_DATA_HOME": str(tmp / "data")}
        env.pop("DAILY_COACH_CONF", None), env.pop("DAILY_COACH_DATA", None)
        return env

    def test_dry_run_in_a_sandbox(self):
        tmp = Path(tempfile.mkdtemp())
        p = subprocess.run([sys.executable, "-I", str(HERE / "run.py"), "--dry-run"], env=self.env(tmp),
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(" 0 unfilled placeholders", p.stdout)
        self.assertIn("model: test-model", p.stdout)
        self.assertRegex(p.stdout, r"guard: .*guard\.py'? .* a\.example b\.example")  # shlex quotes Windows paths

    def test_second_run_waits_for_the_lock(self):
        tmp = Path(tempfile.mkdtemp())
        env = self.env(tmp)
        state = tmp / "state/ivan-the-terminal/daily-coach"
        state.mkdir(parents=True)
        held = run.lock(state / "lock")
        self.addCleanup(held.close)
        p = subprocess.run([sys.executable, "-I", str(HERE / "run.py"), "--dry-run"], env=env, capture_output=True,
                           text=True, encoding="utf-8")
        self.assertEqual(p.returncode, 0)
        self.assertIn("already in progress", p.stdout)


if __name__ == "__main__":
    unittest.main()
