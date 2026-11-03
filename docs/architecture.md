# Architecture

## Two repos, one setup

| | ivan-the-terminal (public) | ivan-the-terrible (private) |
|---|---|---|
| Purpose | portfolio and reusable tooling | what makes it *mine* |
| Contents | skills, `bin/itt`, leakguard, docs | profile, per-skill config, denylist, Claude memory, private skills, sops secrets |
| Lands on disk as | `~/Repositories/ivan-the-terminal` | `~/Repositories/ivan-the-terrible`, linked into `~/.config/ivan-the-terminal/` |

`itt bootstrap` wires it together, idempotently:

- the toolchain from `toolchain.txt` (brew on Linux, winget on Windows; core tools plus per-skill extras)
- skills from `plugins/*/skills/*` (and the overlay's `skills/`) → symlinks in `~/.claude/skills/` (junctions on Windows), so edits are live and work from any directory
- the overlay's `config/ivan-the-terminal/` → `~/.config/ivan-the-terminal/` (private CLAUDE.md, denylist, per-skill config)
- Claude Code auto-memory for listed project directories → the overlay's `memory/` (versioned, follows me to new machines)
- `itt` → `~/.local/bin/itt` (Windows: an `itt.cmd` shim there, added to PATH)
- interactive `claude` starts in this repo: `shell/claude-home.bash` (`~/.bashrc.d`) or `shell/claude-home.ps1` (PowerShell profiles)

## Context loading

`CLAUDE.md` (public, small) ends with `@~/.config/ivan-the-terminal/CLAUDE.md`, the private overlay index. The overlay index only *points* at profile files and doesn't import them, so personal context costs tokens only when a task needs it.

## Skill pattern

```
plugins/<plugin>/skills/<skill>/
  SKILL.md          # what + when, then a short procedure
  scripts/          # deterministic work, terse output (executed, never read into context)
  references/       # detail loaded only when a step says so
  config.example    # shape of the private config at ~/.config/ivan-the-terminal/<skill>.*
```

Skills that run unattended (timers) use headless `claude -p` with a tool allowlist and a guard hook, logging to `~/.local/state/ivan-the-terminal/<skill>/`.

Skills that report something daily (job-digest, daily-coach) email it to their owner. The headless run sends that one email itself, and its guard lets mail go only to the configured address. Feedback comes back as replies, which the next run reads. There are no servers to keep running: on Windows a Task Scheduler task (`run.py --install-task`) runs them, on Linux a systemd timer.

## Portability

Everything that can be is stdlib Python, so the same skills run on Linux and Windows (CI tests both): `itt`, doctor, ship-check, the git hooks, leakguard and the skill scripts. `itt bootstrap` is Python too, with one branch per OS for the package manager, links and services. Work tied to one OS stays native and says so: systemd units, the shell wrappers in `shell/`, and `scripts/run.sh` in skills like homelab-check. Their Windows twins (`.ps1`, Task Scheduler) are tracked in the private backlog.

## Secrets

The overlay uses sops+age. One age key (`~/.config/sops/age/keys.txt`, backed up offline) decrypts everything. Skills consume secrets with `sops exec-env <file> '<cmd>'`, so plaintext never touches disk or the transcript. On Windows, `sops exec-env` hands the command to `cmd.exe` with its quotes escaped, which splits quoted paths that contain spaces. A skill that takes such paths (e.g. add-game) reads the secret file's path from its config and decrypts it in memory with `sops -d` instead. The plaintext still never touches disk, arguments or output.
