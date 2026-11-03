# Roadmap

Skills distilled from months of real sessions, each turned generic here with personal values kept in the overlay.

| Plugin | Skills (planned) | Replaces |
|---|---|---|
| **foundation** ✅ | doctor, new-machine, ship-public, kaizen | manual setup notes |
| **homelab** ✅ | homelab-check (OS, apps, firmware, disks, SMART, mounts, services, containers, tailnet; daily notify) ✅, system-updates ✅, tv ✅ (Android TV over adb: Stremio + boot autostart, SmartTube, Tailscale always-on with tailnet DNS, remote app buttons remapped via Key Mapper; weekly updates), prep-windows11-installation-iso ✅ (debloated unattended Windows 11 USB, silent first-logon apps, key restore) · next: wake-and-power (WoL, idle draw) | vendor apps, "smart" hubs, Microsoft-account-first Windows setup, uptime SaaS, ad-supported YouTube and Play Store-gated TV apps |
| **retro** ✅ | rom-library ✅ (audit, CHD/RVZ, m3u, 50 Hz), rom-sync ✅ (adb / SD), add-game ✅ (launcher → Steam non-Steam game + Apollo/Sunshine app with SteamGridDB art, virtual display, admin and driver cleanup for launch scripts, `--args`/`--batch` for emulators), emulators ✅ (Xenia Canary / RPCS3 / Eden install + update, saves kept in the library via junctions/content_root, keys + firmware, 1440p, 60 fps patches and mods, GAME= list → Steam + Apollo) · next: more systems in emulators (PS2/GC/Wii via PCSX2 + Dolphin), lutris-import (could reuse add-game's art lookup), game-streaming setup (Apollo drivers + primary display + Moonlight over Tailscale), handheld-cfw notes | cloud gaming subscriptions, Steam ROM Manager |
| **career** ✅ | job-digest ✅ (headless Claude once a day after the last LinkedIn alert: feeds, inbox triage, shortlist, reply/outreach drafts, LinkedIn alerts/messages/notifications archived; one emailed digest, the only mail the run can send; Linux timer or Windows task) · next: profile writing | job-board premium tiers, LinkedIn's own email noise |
| **health** ✅ | daily-coach ✅ (ring-sync-triggered headless plan from smart-ring/Apple Health data: exercise snacks, a local seasonal recipe, sleep, rotating measurements; Daily phone app with push, check-ins, XP, comeback bonus, no streaks; trends; no mail access) · next: weekly PDF/print report, partner night-duty view | fitness/sleep app subscriptions, personal-trainer check-ins |
| **civic** ✅ | podai-globata ✅ (Подай глобата: photos of a wrongly parked car in Bulgaria → address, plate, violations with the article of the law, the right authority, and a formal email as a Gmail draft, mailto link or copy text; runs on claude.ai on the phone; zip auto-published on every change) | city signal portals, phone queues, hand-written complaints |
| **inbox** | triage and unsubscribe sweeps | mail "assistants" |
| **kitchen** | chef: seasonal, locally available recipes, pantry-aware, family preferences (daily-coach already picks one recipe a day) | recipe/meal-kit apps |
| **training** | training buddy: progressive overload plans, calendar events (daily-coach covers exercise snacks and check-ins) | fitness subscriptions |
| **media** | convert-for-legacy-players (e.g. Wii), player troubleshooting | streaming add-ons |
| **money** | subscription audit → self-hosted replacements | the subscriptions themselves |

## Windows

Skills are portable Python first (see [skill-authoring.md](skill-authoring.md) rule 12): every skill except homelab-check and system-updates enters through `scripts/run.py`, and CI tests both OSes. `itt bootstrap`, doctor and the interactive-`claude` wrapper (`shell/claude-home.ps1`) work on Windows. Still Linux-only, each to get a Windows twin:

- systemd timers and services → Task Scheduler tasks; doctor's scheduler checks
- headless runs: job-digest runs on Windows (its Bash tool is Git Bash, PowerShell denied, `--install-task`); daily-coach still needs the same (`--serve` and `--dry-run` already work), and its wake `TRIGGER` default is systemd
- homelab-check, system-updates → `run.ps1` (Windows Update, winget, disks, event log)
