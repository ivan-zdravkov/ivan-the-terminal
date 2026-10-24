# Architecture

## Two repos, one setup

| | ivan-the-terminal (public) | ivan-the-terrible (private) |
|---|---|---|
| Purpose | portfolio and reusable tooling | what makes it *mine* |
| Contents | skills, `bin/itt`, leakguard, docs | profile, per-skill config, denylist, Claude memory, private skills, sops secrets |
| Lands on disk as | `~/Repositories/ivan-the-terminal` | `~/Repositories/ivan-the-terrible`, linked into `~/.config/ivan-the-terminal/` |

`itt bootstrap` wires it together, idempotently:

- skills from `plugins/*/skills/*` (and the overlay's `skills/`) → symlinks in `~/.claude/skills/`, so edits are live and work from any directory
- the overlay's `config/ivan-the-terminal/` → `~/.config/ivan-the-terminal/` (private CLAUDE.md, denylist, per-skill config)
- Claude Code auto-memory for listed project directories → the overlay's `memory/` (versioned, follows me to new machines)
- `itt` → `~/.local/bin/itt`

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

Skills that report something daily store the result locally and serve it as a home-screen phone app instead of emailing it. Each runs a stdlib server on localhost, published on the tailnet by `tailscale serve`, with shared offline and push support from `tools/webapp/` (see [phone-apps.md](phone-apps.md)). The headless run only stores the result; the runner script sends the push.

## Secrets

The overlay uses sops+age. One age key (`~/.config/sops/age/keys.txt`, backed up offline) decrypts everything. Skills consume secrets with `sops exec-env <file> '<cmd>'`, so plaintext never touches disk or the transcript.
