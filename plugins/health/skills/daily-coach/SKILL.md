---
name: daily-coach
description: Run, tune or debug the daily health coach - ring/Apple Health data auto-synced from the iPhone, a tiny gamified plan (movement snacks, seasonal recipe, sleep, measurements) pushed to the Daily phone app, check-ins with XP and trends. Use when Ivan asks about his plan, sleep, energy, workouts, food, weight, the Daily app, ring sync or notifications, or says the plan was too much/too easy.
---

# Daily coach

Pieces (all in this skill):
- `scripts/coach.py`: SQLite store, the Daily app (check-in, trends, push), `/ingest` for the iPhone, CLI.
- `scripts/run`: the headless morning run behind `scripts/guard.py`. The run has no mail or MCP tools at all.
- `references/prompt.md` (coaching procedure), `references/method.md` (why it works this way, with sources), `references/iphone-shortcut.md` (ring sync and automations).
- The shared app shell is `tools/webapp/` in the repo, set up as in `docs/phone-apps.md`.

Private: `~/.config/ivan-the-terminal/daily-coach/{config.env,profile.md}` (template: `config.example`). Data: `~/.local/share/ivan-the-terminal/daily-coach/` (coach.db, token, VAPID key, push subscriptions). This is health data: never commit it or paste it anywhere public.

## Flow
1. iPhone automations run the silent "Coach sync" shortcut when the ring app is closed (and when a daily app is opened). It POSTs Health samples to `/ingest`. Health only unlocks while the phone does.
2. The first sync after `AUTO_PLAN_HOUR`, at least 20 min after the night ended, starts `daily-coach.service` (`itt run daily-coach --if-missing`). `daily-coach.timer` runs the same at 10:30 as a fallback.
3. The run reads `coach context` (ring data, check-ins, notes from the app) and stores the plan. The runner then calls `coach notify`, which sends an empty push; the phone fetches the headline from `api/latest`.
4. The Daily app opens on the newest plan. Before today's exists, it shows yesterday's and switches by itself when the new one lands. The note box is the feedback channel; tomorrow's run reads it.

## Common tasks
- **Status and links:** `itt run daily-coach --dry-run` shows config, last sync, metrics, unknown types, today's plan, XP, push devices, and the app/sync/morning URLs (they contain the token). Server: `systemctl --user status daily-coach-server`.
- **Make or remake today's plan now:** `itt run daily-coach`. It takes a few minutes and pushes. Re-planning keeps check-ins on matching item ids.
- **No ring data / `last sync: never`:** walk through `references/iphone-shortcut.md`. If `UNKNOWN type` lines show up, add the name to `METRICS` in `coach.py` (another locale or app), then sync again.
- **No notification / app offline:** follow the troubleshooting table in `docs/phone-apps.md` (`tailscale serve status`, push device count, the 🔔 button).
- **"Too much" / "too easy" / new goal or constraint:** edit the private `profile.md` (goals, equipment, constraints, recipe sites). A note in the app also works: the next run reads it. Change `references/prompt.md` only for generic method changes, and ship those via ship-public.
- **Debug a run:** read the newest log in `~/.local/state/ivan-the-terminal/daily-coach/logs/`. Exit code 3 means it finished without storing a plan.
- **Tests:** `python3 -I -m unittest discover -s scripts`.

## Safety invariants
- The run reads untrusted recipe pages. Never add interpreters, an unrestricted Read/Write, MCP tools (Gmail or any other), or `coach notify`/`serve` to `scripts/run`'s allowlist, and never weaken `guard.py`. WebFetch is limited to `WEB_DOMAINS`.
- The server binds to localhost only; `tailscale serve` (never Funnel) publishes it on the tailnet. Every path sits under the secret `TOKEN`.
- Push subscriptions are accepted only for real push services (`webapp.PUSH_HOSTS`), so the server can't be made to POST anywhere else.
- Not medical advice: the plan nudges, it doesn't diagnose. Illness flags lower the day's load and suggest a doctor when they persist.
