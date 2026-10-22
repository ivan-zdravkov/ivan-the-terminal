---
name: doctor
description: Health-check the ivan-the-terminal setup - toolchain installed and current, GitHub/SSH auth, git hooks and leak guards, private overlay, age key, linked skills and memory. Use when asked to check, verify or update the setup, after an OS update, or when a skill fails for environmental reasons.
---

# Doctor

Run `itt doctor` (fallback: `~/Repositories/ivan-the-terminal/bin/itt doctor`).
It prints only problems as `LEVEL check detail`, then `doctor: all green (N checks)` or a count summary.
Flags: `-v` show passing checks, `--update` upgrade outdated brew tools first.

Fix each problem using its detail hint, then re-run until green. Common fixes:

| check | fix |
|---|---|
| `tool:*` missing / `*-link` / `skill:*` / `git-hooks` | `itt bootstrap` |
| `tool:*` update available | `itt doctor --update` |
| `ssh-passphrase` | Ivan runs `ssh-keygen -p -f ~/.ssh/id_ed25519` in his own terminal (interactive) |
| `private:age-key` | restore the key from the offline backup to `~/.config/sops/age/keys.txt`, `chmod 600` |
| `private:denylist-ci-sync` | `~/Repositories/ivan-the-terrible/bin/sync-denylist` |
| `branch-protection`, `push-protection` | see `references/github-hardening.md` |

Never make a check pass by weakening a guard (removing hooks, emptying the denylist, `--no-verify`).
Interactive or sudo steps: hand Ivan the exact command instead of trying to run it.
