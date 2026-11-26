#!/usr/bin/env python3
"""SessionStart hook: list work an earlier session left unshipped, so this one finishes it.

Checks this repo and the private overlay (the repo behind ~/.config/ivan-the-terminal) for uncommitted changes,
stashes, commits not on their upstream, and local branches never pushed. Offline (no fetch, no gh) and quiet when
everything is shipped. Prints the SessionStart JSON with the findings as additionalContext; never fails the session.
"""
import json
import os
import subprocess
import sys
from pathlib import Path


def git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", timeout=10)
    return r.stdout.strip() if r.returncode == 0 else ""


def overlay_repo():
    link = Path.home() / ".config" / "ivan-the-terminal"
    root = link.resolve().parents[1] if link.exists() else None
    return root if root and (root / ".git").exists() else None


def pending(repo):
    out = []
    dirty = git(repo, "status", "--porcelain")
    if dirty:
        n = len(dirty.splitlines())
        out.append(f"{n} uncommitted change(s) on {git(repo, 'branch', '--show-current') or 'a detached HEAD'}")
    for s in git(repo, "stash", "list").splitlines():
        out.append(f"stash: {s}")
    base = "origin/HEAD" if git(repo, "rev-parse", "--verify", "-q", "origin/HEAD") else "origin/main"
    for line in git(repo, "for-each-ref", "refs/heads",
                    "--format=%(refname:short)|%(upstream:short)|%(upstream:track)").splitlines():
        name, upstream, track = (line.split("|") + ["", ""])[:3]
        if not upstream:
            ahead = git(repo, "rev-list", "--count", f"{base}..{name}") or "0"
            if ahead != "0":
                out.append(f"branch {name}: {ahead} commit(s), never pushed")
        elif "ahead" in track:
            out.append(f"branch {name}: {track} vs {upstream}, not pushed")
    return out


def main():
    here = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[1])
    repos = [("public", here)] + ([("private overlay", overlay_repo())] if overlay_repo() else [])
    lines = [f"- {label} ({repo}): {item}" for label, repo in repos for item in pending(repo)]
    if not lines:
        return
    context = ("Unshipped work from an earlier session (it may have stopped early). Before new work, tell Ivan in one "
               "line, then finish it: public changes go through the ship-public skill (one PR per topic), private "
               "overlay changes are committed and pushed. Pushed branches may still have open PRs: `gh pr list`.\n"
               + "\n".join(lines))
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # a broken check must never block the session
        print(f"pending_work: {e}", file=sys.stderr)
