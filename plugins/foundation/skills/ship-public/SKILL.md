---
name: ship-public
description: Publish changes to the public ivan-the-terminal repo safely - branch, local leak scan, gitleaks, tests, /security-review, push, PR, auto-merge on green. Use for ANY commit, push, PR, issue or release in ivan-the-terminal, and whenever moving content from the private overlay into public.
---

# Ship to the public repo

Pushing a branch publishes it: PR refs stay public even after a squash merge. So every check runs locally before the first push, and CI repeats them.

1. **Classify first.** Anything identifying a person, place, device, network, account or employer belongs in the private overlay (see CLAUDE.md "Data tiers"). Public files use placeholders and read real values from `~/.config/ivan-the-terminal/` at runtime.
2. **Branch:** `git fetch -q && git switch -c <type>/<slug> origin/main` (type: feat, fix, docs, skill, chore).
3. **Commit:** conventional message. Hooks scan staged changes and the message. Never `--no-verify`.
4. **Gate:** `itt ship-check`. It must end with `ship-check: clean`. On findings, fix the content; don't allowlist it unless it's truly generic, like a documentation IP.
5. **Review:** run the `/security-review` skill on the branch and fix anything real. If you changed anything, repeat 3–4.
6. **Push:** `git push -u origin HEAD`. The pre-push hook re-scans.
7. **PR:** `gh pr create --title "<conventional title>" --body-file <tmp>`. The body covers what and why, plus a `Security:` line with the ship-check and security-review results. The PR text is public and scanned too.
8. **Merge:** `gh pr merge --auto --squash --delete-branch`. Required checks: leakguard, gitleaks, tests. Watch with `gh pr checks --watch`. Fix failures on the same branch.
9. **Sync:** `git switch main && git pull --ff-only`. Report the PR URL in one line.

If private data was ever pushed: stop, tell Ivan, and follow SECURITY.md "If something leaks". Rotate first, then purge.
