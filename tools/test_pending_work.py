import subprocess
import tempfile
import unittest
from pathlib import Path

import pending_work


def run(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com",
                    "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)


class Pending(unittest.TestCase):
    def test_reports_dirty_stash_unpushed_and_never_pushed(self):
        with tempfile.TemporaryDirectory() as d:
            origin, repo = Path(d, "origin.git"), Path(d, "repo")
            run(d, "init", "-q", "--bare", "-b", "main", str(origin))
            run(d, "clone", "-q", str(origin), str(repo))
            Path(repo, "a.txt").write_text("1\n", encoding="utf-8")
            run(repo, "add", "a.txt")
            run(repo, "commit", "-qm", "one", "--no-verify")
            run(repo, "push", "-q", "-u", "origin", "main", "--no-verify")
            self.assertEqual([], pending_work.pending(repo))  # everything shipped: quiet

            run(repo, "switch", "-q", "-c", "feat/x")
            Path(repo, "b.txt").write_text("2\n", encoding="utf-8")
            run(repo, "add", "b.txt")
            run(repo, "commit", "-qm", "two", "--no-verify")
            run(repo, "switch", "-q", "main")
            Path(repo, "a.txt").write_text("changed\n", encoding="utf-8")
            run(repo, "stash", "-q")
            Path(repo, "a.txt").write_text("changed again\n", encoding="utf-8")
            Path(repo, "c.txt").write_text("3\n", encoding="utf-8")
            run(repo, "add", "c.txt")
            run(repo, "commit", "-qm", "three", "--no-verify", "--", "c.txt")

            found = "\n".join(pending_work.pending(repo))
            self.assertIn("1 uncommitted change(s) on main", found)
            self.assertIn("stash@{0}", found)
            self.assertIn("branch feat/x: 1 commit(s), never pushed", found)
            self.assertIn("branch main: [ahead 1] vs origin/main, not pushed", found)


if __name__ == "__main__":
    unittest.main()
