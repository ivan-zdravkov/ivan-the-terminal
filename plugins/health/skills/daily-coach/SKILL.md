---
name: daily-coach
description: Run, tune or debug the daily health coach - ring/Health data synced to a private repo with no hands, a tiny gamified plan (movement snacks, recipe, sleep, measurements) emailed each morning, check-ins by replying. Use when Ivan asks about his plan, sleep, energy, workouts, food, weight, the morning email, the Health sync shortcut or ring data, or says it was too much/too easy.
---

# Daily coach

Pieces (all in this skill):
- `scripts/coach.py`: SQLite store (samples, plans, check-ins, XP), the repo import, the email rendering, CLI.
- `scripts/run.py`: the import, the morning schedule, and the headless run behind `scripts/guard.py`.
- `references/prompt.md` (coaching procedure), `references/method.md` (why it works this way, with sources), `references/iphone-health-sync.md` (the phone side, once).

Private:
- Config: `~/.config/ivan-the-terminal/daily-coach/{config.env,profile.md}` (template: `config.example`). It sets `MAIL_TO`, `HEALTH_REPO` (a clone of the private repo the phone commits to), the schedule and the recipe sites.
- Data: `~/.local/share/ivan-the-terminal/daily-coach/coach.db`. It can be rebuilt from the repo's `health/` files, except check-ins, which live in the email replies.
- This is health data: never commit it to the public repo or paste it anywhere public.

## Flow
1. The iPhone's "Health sync" shortcut runs silently whenever Ivan opens an everyday app, at most every 2 h. It commits the last day of Health samples to `HEALTH_REPO` under `health/YYYY/MM/`. iOS only unlocks Health while the phone is unlocked.
2. From `AUTO_PLAN_HOUR` the schedule runs `run.py --if-ready` every 15 min:
   - Windows: the Task Scheduler task `daily-coach`.
   - Linux: `daily-coach.timer`.
   Each run fetches the repo and imports new files, reading them from `origin/main` without touching the clone's working tree.
3. The plan is made once last night's sleep has arrived and ended 20+ min ago, or at `PLAN_BY` at the latest. The run does three things:
   - turns replies to recent "Daily plan" emails into check-ins
   - reads `coach context`
   - stores the plan, renders it with `coach email` and sends it to `MAIL_TO`
4. Ivan replies to the email in any words ("did the swings, weight 91.8, energy 4"). Tomorrow's run counts the reply.

## Common tasks
- **Status:** `itt run daily-coach --dry-run` shows config, last import, samples per metric, unknown types, last night, readiness, today's plan and XP.
- **What arrived from the phone:** `itt run daily-coach --import`.
- **Make or remake today's plan now:** `itt run daily-coach`. It takes a few minutes and sends the email. Re-planning keeps check-ins on matching item ids.
- **Schedule:** Windows: `itt run daily-coach --install-task` (rerun it after changing `AUTO_PLAN_HOUR` or `PLAN_BY`). Check it with `Get-ScheduledTaskInfo daily-coach`.
- **No ring data / no files in the repo:** walk through `references/iphone-health-sync.md`. If `UNKNOWN type` lines show up, add the name to `METRICS` in `coach.py` (another locale or app), then import again.
- **"Too much" / "too easy" / new goal or constraint:** a reply to the plan email works, and so does editing the private `profile.md` (goals, equipment, constraints, recipe sites). Change `references/prompt.md` only for generic method changes, and ship those via ship-public.
- **Debug a run:** read the newest log in `~/.local/state/ivan-the-terminal/daily-coach/logs/`. Exit code 3 means it finished without storing a plan.

## Safety invariants
- The run reads untrusted recipe pages and mail. Never add these to `scripts/run.py`'s allowlist:
  - interpreters, or an unrestricted Read/Write
  - other MCP tools, or Gmail drafts, labels, replies or forwards
  - `coach.py import`
  And never weaken `guard.py`. WebFetch is limited to `WEB_DOMAINS`. Mail goes only to `MAIL_TO`, with a "Daily plan" subject.
- The phone's GitHub token can write to the whole `HEALTH_REPO` repo (GitHub can't limit it to a folder). Scope it to that one repo, contents only, with an expiry.
- Not medical advice: the plan nudges, it doesn't diagnose. Illness flags lower the day's load and suggest a doctor when they persist.
