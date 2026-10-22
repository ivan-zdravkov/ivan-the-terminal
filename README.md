# ivan-the-terminal

> A self-hosted copilot that lives in my terminal. Claude Code skills that keep my home infrastructure in order, my retro game library playable and streamable, my job search moving, my kitchen fed and my training on track. Each one is built to replace a subscription.

The name? Ivan the Terrible had secrets. This repo is **Ivan the Terminal**: everything that's safe to share. The secrets live in a private sibling.

## Why

- **Own the stack.** Every skill replaces a paid, ad-driven or enshittified service with something local, scriptable and mine.
- **Lean on tokens.** Skills are short, push deterministic work into scripts with terse output, and load details only on demand. ([conventions](docs/skill-authoring.md))
- **Private by construction.** Public skills are generic. Personal values are injected at runtime from a private overlay, and a multi-layer guard stops anything personal from reaching this repo.

## How it fits together

```mermaid
flowchart LR
  subgraph public["ivan-the-terminal (public)"]
    S[skills] --> B[bin/itt]
    L[leakguard]
  end
  subgraph private["ivan-the-terrible (private)"]
    P[profile + config]
    M[Claude memory]
    X[secrets<br/>sops + age]
  end
  P -- "~/.config/ivan-the-terminal" --> S
  X -- "sops exec-env" --> S
  L -. "blocks tier 1/2 data" .-> public
```

| Tier | Where | Examples |
|---|---|---|
| 0 · public | this repo | skills, scripts, docs, ideas |
| 1 · private | overlay repo | family, schedules, addresses, network topology, devices, paths |
| 2 · encrypted | overlay, sops+age | API keys, passwords, tokens |

## Leak defence in depth

| Layer | When | What |
|---|---|---|
| Claude `PreToolUse` hook | before Claude writes a file here or runs `gh pr/issue/…` | leakguard on the content |
| `pre-commit` / `commit-msg` | every commit | leakguard (staged lines, message) + gitleaks |
| `pre-push` | before anything leaves the machine | leakguard on every outgoing commit + gitleaks on full history; direct pushes to `main` refused |
| `ship-public` skill | every change | `itt ship-check` + `/security-review` before the first push |
| CI (`guard.yml`) | every PR, required to merge | leakguard (tree, every commit, PR text) with the private denylist from an encrypted secret, gitleaks, tests |
| GitHub | always | protected `main`, secret scanning + push protection, read-only Actions token, pinned actions |

[leakguard](tools/leakguard/leakguard.py) is a dependency-free Python scanner with two parts. Generic rules catch IPs, MACs, phone numbers, home paths, tailnet names, private keys, IBANs, coordinates and image EXIF. A **private denylist** covers names, places, serials, and sha256-hashed secrets, so even the denylist never stores credentials in plaintext. See [SECURITY.md](SECURITY.md).

## Plugins

| Plugin | Skills | Status |
|---|---|---|
| [foundation](plugins/foundation) | `doctor`, `new-machine`, `ship-public`, `kaizen` | ✅ |
| [homelab](plugins/homelab) | `homelab-check` (daily, notifies), `system-updates` | ✅ |
| retro, career, kitchen, training, … | see the [roadmap](docs/roadmap.md) | 🛠️ |

## Use it

```bash
# as a Claude Code plugin marketplace
/plugin marketplace add ivan-zdravkov/ivan-the-terminal
/plugin install foundation@ivan-the-terminal

# or the full setup (Linux + Homebrew)
gh repo clone ivan-zdravkov/ivan-the-terminal ~/Repositories/ivan-the-terminal
~/Repositories/ivan-the-terminal/bin/itt bootstrap && itt doctor
```

Without a private overlay everything runs in generic mode. To make it yours, create your own overlay repo and point `ITT_PRIVATE_REPO` at it.

Built on Linux (Bazzite, atomic Fedora) with [Claude Code](https://claude.com/claude-code). MIT licensed.
