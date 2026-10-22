---
name: homelab-check
description: Health-check the home machine - OS image and pending reboot, app/firmware updates, disk space, SMART, nofail mounts (e.g. a dirty NTFS backup drive), failed or watched systemd units, containers, DNS/internet, tailnet peers. Use when something "stopped working", games or ROMs are missing, streaming or a service fails, before or after updates, or when asked how the machine is doing.
---

# Homelab check

Run `itt run homelab-check`. Flags: `-v` show all checks, `--json` machine-readable output.
It prints problems only, as `LEVEL check detail`, plus a summary line. A daily timer runs it with `--notify`; the last result is in `~/.local/state/ivan-the-terminal/homelab-check/last.txt`. Read that first if Ivan asks about an earlier notification.

Fix by check prefix. For anything not obvious, read `references/remediation.md`.
- `mount:*` not mounted → check this **first** when apps or emulators can't find their files.
- `os-reboot` → ask Ivan before rebooting. Never reboot on your own.
- `disk:*` → suggest what to clean, but never delete without asking.
- `unit:*` / `watch:*` / `container:*` → read the journal, fix the cause, then restart.

Sudo or interactive steps: give Ivan the exact command to run with `!`.
Configure watched units, containers, peers, thresholds and skipped modules in `~/.config/ivan-the-terminal/homelab.conf` (template: `config.example`).
When a new service or timer gets set up, add it to `WATCH_*` in that config.
