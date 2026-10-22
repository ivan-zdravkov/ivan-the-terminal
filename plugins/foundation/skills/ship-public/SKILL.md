---
name: ship-public
description: Publish changes to the public ivan-the-terminal repo safely - branch, local leak scan, gitleaks, tests, /security-review, push, PR, auto-merge on green. Use for ANY commit, push, PR, issue or release in ivan-the-terminal, and whenever moving content from the private overlay into public.
---

# Ship to the public repo

Pushing a branch publishes it: PR refs stay public even after a squash merge. So every check runs locally before the first push, and CI repeats them.

1. **Classify first.** Anything identifying a person, place, device, network, account or employer belongs in the private overlay (see CLAUDE.md "Data tiers"). Public files use placeholders and read real values from `~/.config/ivan-the-terminal/` at runtime.
2. **Branch:** `git fetch -q && git switch -c <type>/<slug> origin/main` (type: feat, fix, docs, skill, chore).
3. **Commit:** conventional message. Hooks scan staged changes and the message. Never `--no-verify`.
4. **Interview:** `itt guard candidates origin/main HEAD` lists terms that *might* be personal (names, places, clubs, numbers, handles). Drop the obviously generic ones yourself (products, tools, standards). Ask Ivan about the rest with AskUserQuestion, multiSelect "Which of these are private?", up to 4 terms per question with each term's context in its description.
   - Private: `~/Repositories/ivan-the-terrible/bin/denylist-add "<term>"`, then `bin/sync-denylist`, then fix the content.
   - Public: append to `.leakguard-reviewed` so it's never asked again.
   - Bank details are never public. Don't even ask; remove them.
5. **Gate:** `itt ship-check`. It must end with `ship-check: clean`. On findings, fix the content; don't allowlist it unless it's truly generic, like a documentation IP.
6. **Review:** run the `/security-review` skill on the branch and fix anything real. If you changed anything, repeat 3–5.
7. **Push:** `git push -u origin HEAD`. The pre-push hook re-scans.
8. **PR:** `gh pr create --title "<conventional title>" --body-file <tmp>`. The body covers what and why, plus a `Security:` line with the interview, ship-check and security-review results. The PR text is public and scanned too.
9. **Merge:** `gh pr merge --auto --squash --delete-branch`. Required checks: leakguard, gitleaks, tests. Watch with `gh pr checks --watch`. Fix failures on the same branch.
10. **Sync:** `git switch main && git pull --ff-only`. Report the PR URL in one line.

If private data was ever pushed: stop, tell Ivan, and follow SECURITY.md "If something leaks". Rotate first, then purge.
