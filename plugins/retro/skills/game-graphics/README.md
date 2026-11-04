# game-graphics

Your PC games set up for **your** rig and **your** taste. You give it an fps target per genre, the effects you hate
and the tools you allow. It researches each game, writes the settings into the game's own config files (with
backups) and brings modern upscaling to games that lack it. A daily unattended pass does the same for every new or
updated game and emails you what changed.

```text
itt run game-graphics scan
itt run game-graphics apply plan.json
```

Replaces: GeForce Experience / AMD "optimize" buttons (which tune for the vendor's idea of quality), reading a
settings guide for every game, hand-installing OptiScaler, and forgetting to switch off motion blur again.

## What it does

| Piece | What it does |
|---|---|
| `scan` | Finds games in Steam, Epic, GOG, Ubisoft, EA, Battle.net, Xbox and your own folders. Reports their upscaler DLLs (FSR 3.1, DLSS, XeSS, frame gen), engine and anti-cheat, and flags new or updated games |
| `apply` | Writes a plan into the game's config: ini, WoW `Config.wtf`, Call of Duty `players/*.txt`, Forza `UserConfigSelections`, JSON. Backs up first, refuses while the game runs, validates values (CoD) and only touches text configs under game dirs, Documents or AppData |
| `diff` / `restore` | What changed since the plan (to learn a game's menu encoding), and one-command undo |
| `optiscaler` | Installs [OptiScaler](https://github.com/optiscaler/OptiScaler) (latest stable, sha256-checked) to swap DLSS/XeSS/FSR 2-3 for FSR 4 and add frame gen. Backs up the files it replaces, never overwrites another mod's proxy DLL, refuses anti-cheat and online games, and updates every install in one go |
| `system` | Windows checks: HAGS, Game Mode, windowed-game optimisations, games pinned to the dedicated GPU, RAM below its rated speed (EXPO/XMP off). `--apply` fixes what lives in HKCU |
| `daily` | Headless `claude -p` pass: researches and tunes new or updated games (5 a day), keeps OptiScaler current, emails a short report only when something changed |

## The knowledge it uses

- [`references/settings.md`](references/settings.md): every common setting, what it does, what it typically costs,
  whether you'd notice, and the default rule. Also the order of cuts and how to tell a CPU-bound game.
- [`references/upscaling.md`](references/upscaling.md): the AMD ladder (native FSR 4 → driver FSR 4 upgrade →
  OptiScaler → TAA), frame gen choices (ML FG, OptiScaler FSR FG, AFMF, Lossless Scaling) and Adrenalin settings.
- [`references/games.md`](references/games.md): per-game config files, encodings and measured costs (WoW, Call of
  Duty, Forza Horizon 6, AC Black Flag Resynced so far).

The defaults reflect the usual verdicts:
- temporal AA always (spatial AA leaves dithered hair and fire grainy)
- VRS off
- Ultra → High on volumetrics, shadows and GI first
- ray tracing only when it transforms the game
- frame gen only in single-player games from a 60 fps base

## Setup

1. Copy [config.example](config.example) to `~/.config/ivan-the-terminal/game-graphics/config.env` and write
   `profile.md` next to it: your rig, fps tiers, kill list, allowed tools.
2. Run `itt run game-graphics scan`. Add folders with manually installed games to `EXTRA_DIRS`.
3. Ask Claude to tune a game, or tune everything that `scan` lists as new.
4. Optional, daily pass (Windows): `itt run game-graphics --install-task`. It needs Claude Code with the Gmail
   connector for the report. Check it with `itt run game-graphics daily --dry-run`.

## Usage

```text
itt run game-graphics scan [--all] [--json]
itt run game-graphics peek "<config file>"
itt run game-graphics apply <plan.json> [--dry-run]
itt run game-graphics diff <slug>
itt run game-graphics restore <slug> [<stamp>]
itt run game-graphics backups [<slug>]
itt run game-graphics optiscaler latest|status|update
itt run game-graphics optiscaler install "<game dir>" [--proxy dxgi] [--set Section.Key=Value ...] [--dry-run]
itt run game-graphics optiscaler remove "<game dir>"
itt run game-graphics system [--apply]
itt run game-graphics daily [--dry-run]
itt run game-graphics --install-task
```

Plan format: [`references/plan.md`](references/plan.md).

## Safety

- **Backups and undo.** Every write is backed up per game and per run (the last 15 are kept), and `restore` puts
  them back. OptiScaler's replaced files are restored by `remove`.
- **Where it writes.** Only existing text configs with a config extension, under a scanned game folder, Documents,
  Saved Games or AppData. Never browser, credential, Microsoft or Claude folders. Never executables.
- **Anti-cheat.** It never injects DLLs into games with anti-cheat (EasyAntiCheat, BattlEye, Ricochet, Vanguard,
  ...) or into online-only games (Battle.net). The driver's own FSR 4 / frame gen overrides are the safe route
  there.
- **The daily run** reads web pages, so it's treated as prompt-injectable. A guard lets it run only this skill's
  script (no `restore`, no `--force-offline`), write only to its work folder, and email only you, as plain HTML.

## Troubleshooting

- **Settings reverted.** Some games rewrite their config on exit, so close the game before `apply`. For a menu
  value that the plan couldn't set (`manual` list), set it in game and run `diff` to learn the encoding.
- **OptiScaler overlay doesn't show.** Try another proxy name: `optiscaler remove`, then `install --proxy winmm`.
  Check the OptiScaler wiki's compatibility list for the game.
- **Game crashes after OptiScaler.** Run `optiscaler remove "<dir>"` and the original files come back.
