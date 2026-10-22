# ivan-the-terminal

Public (MIT) home of Ivan's Claude Code skills, scripts and docs: a self-hosted copilot for home infrastructure, retro gaming, career, kitchen and training. The goal is to replace paid or enshittified services with things he owns.

## Data tiers: decide before writing anything here
- **Tier 0, this repo (public):** generic, reusable, safe for anyone to read.
- **Tier 1, private overlay** (`ivan-the-terrible`, imported below): personal facts, family, addresses, schedules, network topology, devices, serials, home paths, employer, rates.
- **Tier 2, encrypted** (sops+age inside the overlay): credentials, keys, tokens.

If a value identifies a person, place, device, network, account or employer, it is not tier 0.
Use placeholders instead (`~`/`$HOME`, `192.0.2.x`, `example.com`, `<tablet-serial>`) and read real values at runtime from `~/.config/ivan-the-terminal/`.

Never publish bank details (IBAN, card or account numbers, BIC with an account) in any form, not even as examples.

## Every session
- Check the available skills first and use a matching one instead of improvising. If a repeatable task has no skill, say so and offer to write one.
- End substantial tasks, and casual sessions, with a short **kaizen** pass: improve the public or private skills, docs and tools you touched, and log bigger ideas to the private backlog.
- What you learn about Ivan or the setup goes to the overlay (memory/profile), never into this repo.

## Publishing (mandatory)
Pushing a branch publishes it. Use the **ship-public** skill for every commit, push, PR, issue or release: branch → `itt ship-check` → `/security-review` → push → PR → auto-merge on green.
Never push to main, never `--no-verify`, never weaken leakguard to get past a finding.

## Layout
- `plugins/<plugin>/skills/<skill>/` — skills (marketplace: `.claude-plugin/marketplace.json`)
- `bin/itt` — CLI: `doctor`, `bootstrap`, `ship-check`, `guard`
- `tools/leakguard/` — personal-data scanner behind the git hooks, CI and the Claude PreToolUse hook
- `docs/` — architecture, skill-authoring conventions (follow them), roadmap

@~/.config/ivan-the-terminal/CLAUDE.md
