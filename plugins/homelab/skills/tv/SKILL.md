---
name: tv
description: Manage the Android / Google TV over adb - install and update sideloaded apps from their official sources (Stremio, SmartTube ad-free YouTube, Tailscale), open Stremio on power-on, keep Tailscale always-on so DNS goes through the tailnet; weekly update timer. Use when Ivan asks about the TV, its apps, YouTube ads, Stremio, or the TV on Tailscale.
---

# TV

Replaces: the stock YouTube app's ads, Play Store-gated updates and the ad-filled Google TV home as the first screen.
Config: `~/.config/ivan-the-terminal/tv.conf` (template: `config.example`). The TV needs Network debugging on (Developer options).

- `itt run tv status` shows outdated or missing apps and settings drift (problems only; `-v` shows all).
- `itt run tv update [app...]` installs missing apps and updates outdated ones (`--dry-run` to preview). Checksums are verified when the source publishes them (SmartTube, Tailscale).
- `itt run tv setup` (idempotent) gives the boot helper its permissions and makes Tailscale the always-on VPN.
- `itt run tv connect` connects adb. It falls back to mDNS when the TV's IP changed; then update `TV_ADB`.

The weekly update runs from `tv-update.timer`: it fires daily, but works at most once per `WEEKLY_DAYS`, so it retries while the TV is off. It skips an app that is open on screen and notifies on problems. Its last result is in `~/.local/state/ivan-the-terminal/tv/last.txt`.
Install it with `ln -sf $ITT/plugins/homelab/systemd/tv-update.{service,timer} ~/.config/systemd/user/ && systemctl --user enable --now tv-update.timer`, then add `tv-update.timer` to `WATCH_USER_UNITS` in homelab.conf.

## First-time setup (new TV)
1. Turn on Developer options, then Network debugging, and accept the adb prompt on the TV. Reserve the TV's IP in the router.
2. Run `itt run tv update`, then `itt run tv setup`.
3. Tailscale login needs Ivan: open Tailscale on the TV (`adb shell monkey -p com.tailscale.ipn -c android.intent.category.LEANBACK_LAUNCHER 1`), press Log in, and he scans the QR code. Run `setup` again afterwards. It reports `vpn ... connected`.
4. Check DNS: `adb shell dumpsys connectivity | grep -A3 'VPN'`. The VPN's DNS should be Tailscale's quad-100 MagicDNS resolver, which forwards to the tailnet's global resolvers.

## Fixes
- `adb` unreachable: the TV is in deep standby or off, Network debugging is off after a firmware update, or the adb key was revoked. Ask Ivan to wake the TV and accept the prompt.
- Install fails with `INSTALL_FAILED_UPDATE_INCOMPATIBLE`: the signing key changed. Stop here. Never uninstall to force it; check the project's announcements first. SmartTube moved to `org.smarttube.stable` after its 2025 key leak.
- Stremio doesn't open on power-on: the helper only fires on a cold boot. Run `setup` and check `autostart`. For wake from standby, Projectivy Launcher's startup-app option covers it; ask before replacing the launcher.
- Ads in SmartTube: update it. Its ad blocking depends on keeping up with YouTube changes, and NextDNS cannot block YouTube ads.
For sources, package names and why these apps, read `references/apps.md`.
