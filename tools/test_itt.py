import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


itt = load(ROOT / "bin/itt", "itt")
run_tests = load(ROOT / "tools/run_tests.py", "run_tests")
toolchain = load(ROOT / "tools/toolchain.py", "toolchain")
bootstrap = load(ROOT / "bin/bootstrap.py", "bootstrap")


class EntryPoint(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(setattr, itt, "ITT_HOME", itt.ITT_HOME)
        itt.ITT_HOME = self.tmp

    def skill(self, name, *files):
        d = self.tmp / "plugins/p/skills" / name / "scripts"
        d.mkdir(parents=True)
        for f in files:
            (d / f).write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        return d

    def test_portable_python_wins(self):
        d = self.skill("both", "run.py", "run.sh", "run.ps1")
        self.assertEqual(itt.entry_point("both"), d / "run.py")

    def test_native_script_per_os(self):
        d = self.skill("native", "run.sh", "run.ps1")
        self.assertEqual(itt.entry_point("native"), d / ("run.ps1" if itt.WINDOWS else "run.sh"))

    def test_unknown_or_unsafe_names(self):
        self.skill("real", "run.py")
        for name in ("missing", "../real", "*", "re*l", "", "Real"):
            self.assertIsNone(itt.entry_point(name), name)


class Command(unittest.TestCase):
    def test_interpreters(self):
        tmp = Path(tempfile.mkdtemp())
        py, sh, ps1, bare = tmp / "run.py", tmp / "run.sh", tmp / "run.ps1", tmp / "doctor"
        for f in (py, sh, ps1):
            f.write_text("x\n", encoding="utf-8")
        bare.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        self.assertEqual(itt.command(py, ["a"]), [sys.executable, "-I", str(py), "a"])
        self.assertEqual(itt.command(bare, []), [sys.executable, "-I", str(bare)])
        self.assertEqual(itt.command(sh, ["-v"]), [str(sh), "-v"])
        self.assertEqual(itt.command(ps1, []), ["pwsh", "-NoProfile", "-File", str(ps1)])

    def test_cli(self):
        p = subprocess.run([sys.executable, "-I", str(ROOT / "bin/itt"), "help"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        self.assertIn("usage: itt", p.stdout)
        p = subprocess.run([sys.executable, "-I", str(ROOT / "bin/itt"), "run", "no-such-skill"], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("no runnable skill", p.stderr)


class Hooks(unittest.TestCase):
    def test_pre_push_refuses_main(self):
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        env = {k: v for k, v in os.environ.items() if k != "ITT_ALLOW_MAIN_PUSH"}
        p = subprocess.run([sys.executable, str(ROOT / ".githooks/pre-push"), "origin", "x"], cwd=ROOT, env=env,
                           input=f"refs/heads/x {head} refs/heads/main {'0' * 40}\n", capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("main only changes through PRs", p.stderr)


class Toolchain(unittest.TestCase):
    def test_every_row_is_complete(self):
        rows = toolchain.read()
        self.assertIn("python3", [r["cmd"] for r in rows])
        for r in rows:
            self.assertIn(r["tier"], ("core", "extra"), r["cmd"])
            self.assertTrue(r["purpose"] and (r["brew"] or r["winget"]), r["cmd"])
            if r["winget"]:
                self.assertRegex(r["winget"], r"^[\w-]+(\.[\w-]+)+$")

    def test_dash_means_unmanaged(self):
        f = Path(tempfile.mkdtemp()) / "toolchain.txt"
        f.write_text("# header\nx  -  Some.Id  extra  %A%\\b  does  two things\n", encoding="utf-8")
        (row,) = toolchain.read(f)
        self.assertEqual(row, {"cmd": "x", "brew": None, "winget": "Some.Id", "tier": "extra",
                               "win_dir": "%A%\\b", "purpose": "does  two things"})
        self.assertIsNone(toolchain.package(row, windows=False))
        self.assertEqual(toolchain.package(row, windows=True), "Some.Id")


class Link(unittest.TestCase):
    def test_link_backs_up_once_and_is_idempotent(self):
        tmp = Path(tempfile.mkdtemp())
        target, other, path = tmp / "target", tmp / "other", tmp / "deep" / "link"
        target.mkdir(), other.mkdir()
        path.mkdir(parents=True)
        (path / "old.txt").write_text("x", encoding="utf-8")
        bootstrap.link(target, path)
        self.assertEqual(os.path.realpath(path), os.path.realpath(target))
        self.assertEqual(len(list(path.parent.glob("link.pre-itt.*"))), 1)
        bootstrap.link(target, path)  # unchanged
        bootstrap.link(other, path)  # repointed, nothing backed up
        self.assertEqual(os.path.realpath(path), os.path.realpath(other))
        self.assertEqual(len(list(path.parent.glob("link.pre-itt.*"))), 1)
        self.assertTrue(target.is_dir())  # the old target survives the repoint


class Classify(unittest.TestCase):
    def test_python_and_shell_detection(self):
        tmp = Path(tempfile.mkdtemp())
        files = {"a.py": "x = 1\n", "itt": "#!/usr/bin/env python3\n", "safe": "#!/usr/bin/env -S python3 -I\n",
                 "run.sh": "echo\n", "rc.bash": "f() { :; }\n", "hook": "#!/usr/bin/env bash\n", "posix": "#!/bin/sh\n",
                 "notes": "plain text\n", "data.json": "{}\n"}
        for name, text in files.items():
            (tmp / name).write_text(text, encoding="utf-8")
        paths = [tmp / n for n in files]
        self.assertEqual({p.name for p in run_tests.python_files(paths)}, {"a.py", "itt", "safe"})
        self.assertEqual({p.name for p in run_tests.shell_files(paths)}, {"run.sh", "rc.bash", "hook", "posix"})


if __name__ == "__main__":
    unittest.main()
