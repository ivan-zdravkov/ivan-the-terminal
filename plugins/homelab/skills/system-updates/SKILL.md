---
name: system-updates
description: Show or apply pending updates across every layer of an atomic Fedora / Bazzite machine - OS image (staged, reboot), Flatpak apps, Homebrew, distrobox containers, firmware. Use when asked to update the system, check for updates, or after homelab-check reports pending updates or a staged image.
---

# System updates

1. `itt run system-updates` lists each layer's status. Report it in one short block.
2. Ask Ivan before applying anything. Then:
   - user-level layers: `itt run system-updates --apply` (add `--containers` for distrobox; it's slow)
   - OS image: if something is staged, Ivan reboots when convenient (`systemctl reboot`). For a full manual run: `ujust update` (asks for a password; Ivan runs it with `!`).
   - firmware: `fwupdmgr update`. It's interactive and may reboot, so Ivan runs it.
3. Never reboot, and never run sudo yourself.
4. Finish with `itt run homelab-check` to confirm everything is green.

Bazzite's `uupd` timer already updates the OS, Flatpak and brew daily. This skill is for checking now, or forcing it.
