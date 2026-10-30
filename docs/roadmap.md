# Roadmap

Skills distilled from months of real sessions, each turned generic here with personal values kept in the overlay.

| Plugin | Skills (planned) | Replaces |
|---|---|---|
| **foundation** ✅ | doctor, new-machine, ship-public, kaizen | manual setup notes |
| **homelab** ✅ | homelab-check (OS, apps, firmware, disks, SMART, mounts, services, containers, tailnet; daily notify) ✅, system-updates ✅, tv ✅ (Android TV over adb: Stremio + boot autostart, SmartTube, Tailscale always-on with tailnet DNS; weekly updates) · next: wake-and-power (WoL, idle draw) | vendor apps, "smart" hubs, uptime SaaS, ad-supported YouTube and Play Store-gated TV apps |
| **retro** ✅ | rom-library ✅ (audit, CHD/RVZ, m3u, 50 Hz), rom-sync ✅ (adb / SD) · next: emulator-patches, lutris-import (+ SteamGridDB art), game-streaming (Sunshine/Polaris + Moonlight over LAN/Tailscale), handheld-cfw notes | cloud gaming subscriptions |
| **career** ✅ | job-digest ✅ (headless Claude on a timer: feeds, inbox triage, shortlist, reply/outreach drafts; digest in the Jobs phone app with push and Applied/Later/Not-for-me marks; the run can't send mail) · next: profile writing | job-board premium tiers, email digests |
| **health** ✅ | daily-coach ✅ (ring-sync-triggered headless plan from smart-ring/Apple Health data: exercise snacks, a local seasonal recipe, sleep, rotating measurements; Daily phone app with push, check-ins, XP, comeback bonus, no streaks; trends; no mail access) · next: weekly PDF/print report, partner night-duty view | fitness/sleep app subscriptions, personal-trainer check-ins |
| **civic** ✅ | podai-globata ✅ (Подай глобата: photos of a wrongly parked car in Bulgaria → address, plate, violations with the article of the law, the right authority, and a formal email as a Gmail draft, mailto link or copy text; runs on claude.ai on the phone; zip auto-published on every change) | city signal portals, phone queues, hand-written complaints |
| **inbox** | triage and unsubscribe sweeps | mail "assistants" |
| **kitchen** | chef: seasonal, locally available recipes, pantry-aware, family preferences (daily-coach already picks one recipe a day) | recipe/meal-kit apps |
| **training** | training buddy: progressive overload plans, calendar events (daily-coach covers exercise snacks and check-ins) | fitness subscriptions |
| **media** | convert-for-legacy-players (e.g. Wii), player troubleshooting | streaming add-ons |
| **money** | subscription audit → self-hosted replacements | the subscriptions themselves |

## Windows

Skills are portable Python first (see [skill-authoring.md](skill-authoring.md) rule 12). Still Linux-only, each to get a PowerShell twin:

- `itt bootstrap` → `bin/bootstrap.ps1`: winget/scoop toolchain, skill links, `itt` shim on PATH
- systemd timers and services → Task Scheduler tasks; doctor's scheduler checks
- headless runs (daily-coach, job-digest) → allowlist and guard for the PowerShell tool
- homelab-check, system-updates → `run.ps1` (Windows Update, winget, disks, event log)
- `shell/claude-home.bash` → PowerShell profile; the leakguard Claude hook command in `.claude/settings.json`
