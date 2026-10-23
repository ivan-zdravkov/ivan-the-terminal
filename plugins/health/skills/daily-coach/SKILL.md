---
name: daily-coach
description: Run, tune or debug the daily health coach - ring/Apple Health data in, a tiny gamified daily plan (movement snacks, a seasonal recipe, sleep, measurements) out by email, ticked off on a phone page with XP and trends. Use when Ivan asks about his plan, sleep, energy, workouts, food, weight, the check-in page, the morning shortcut, or says the plan was too much/too easy.
---

# Daily coach

Pieces (all in this skill): `scripts/coach.py` (SQLite store, phone check-in page, trends dashboard, `/ingest` for the iPhone, CLI), `scripts/run` (headless morning run behind `scripts/guard.py`), `references/prompt.md` (the coaching procedure), `references/method.md` (why it works this way, with sources), `references/iphone-shortcut.md` (phone setup).
Private: `~/.config/ivan-the-terminal/daily-coach/{config.env,profile.md}` (template: `config.example`). Data: `~/.local/share/ivan-the-terminal/daily-coach/coach.db` (health data: never commit or paste it anywhere public).

## Flow
1. Ivan gets up and runs the "Good morning" shortcut (Action button or alarm-stopped automation). It POSTs last night's Health samples to `/ingest?wake=1`.
2. The server (`daily-coach-server.service`) stores them and starts `daily-coach.service`, which runs `itt run daily-coach --if-missing`. `daily-coach.timer` runs the same as a mid-morning fallback.
3. The run reads `coach context` plus his replies to earlier plan emails, writes the plan, and emails it with the subject `[daily-coach] …`.
4. He ticks items off on the page, and trends are at `…/dashboard`. `--dry-run` prints both URLs. The secret token is in the data dir. Check-ins feed tomorrow's plan.

## Common tasks
- **Status:** `itt run daily-coach --dry-run` shows the config, last sync, metrics seen, unknown sample types, today's plan and XP. Server: `systemctl --user status daily-coach-server`.
- **Make or remake today's plan now:** `itt run daily-coach`. It takes a few minutes and sends an email. Re-planning keeps check-ins on matching item ids.
- **No ring data:** check the last sync in status. If the shortcut never posted, walk through `references/iphone-shortcut.md`. If `UNKNOWN type` lines show up, add the name to `METRICS` in `coach.py` (another locale or app), then re-run the shortcut.
- **"Too much" / "too easy" / new goal or constraint:** edit the private `profile.md` (goals, equipment, constraints, recipe sites). Change `references/prompt.md` only for generic method changes, and ship those via ship-public. A reply to the plan email also works: the next run reads it.
- **Debug a run:** read the newest log in `~/.local/state/ivan-the-terminal/daily-coach/logs/`. Exit code 3 means it finished without storing a plan.
- **Tests:** `python3 -I -m unittest discover -s scripts`.

## Safety invariants
The run reads untrusted recipe pages. Never add interpreters, an unrestricted Read/Write, or Gmail tools beyond search_threads/get_thread/send_message to `scripts/run`, and never weaken `guard.py`. It sends only to `DIGEST_TO`, only with the `[daily-coach]` subject tag. Gmail search is limited to the one plan-thread query, and WebFetch to `WEB_DOMAINS`.
The server only answers under the secret `TOKEN` path. Bind it to localhost and the tailnet IP only, never to a public interface.
Not medical advice: the plan nudges, it doesn't diagnose. Illness flags lower the day's load and suggest a doctor when they persist.
