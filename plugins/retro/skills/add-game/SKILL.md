---
name: add-game
description: Add a PC game's launcher (.exe/.bat/.cmd) to Steam as a non-Steam game and to Apollo/Sunshine for Moonlight streaming, both with art (SteamGridDB, else official Steam store art; IGDB cover for Apollo). Use when Ivan installs a game and wants it in Steam, in Apollo/Moonlight, with box art, or asks to remove or list such games.
compatibility: Steam part runs on Windows and Linux; the Apollo part writes Apollo's Windows config (one UAC prompt) or a user-writable Sunshine config elsewhere.
---

# Add game

Replaces: Steam ROM Manager / manual "Add a Non-Steam Game" + SteamGridDB browsing, and hand-editing Apollo's apps.json.
Config: `~/.config/ivan-the-terminal/add-game.conf` (template: `config.example`; defaults fit a stock Windows install).
Secret: `STEAMGRIDDB_API_KEY`. The script decrypts it in memory from `SGDB_SECRET` (a sops file) with `sops -d`; don't wrap the call in `sops exec-env`, which breaks quoted paths with spaces on Windows. Without a key it falls back to Steam store art (no logos or icons).

1. Read a `.bat`/`.cmd` launcher before adding it: it runs as Ivan, and as admin if it self-elevates.
2. Ask before restarting Steam if Ivan might be playing: `add` and `remove` close Steam (`-shutdown`), write and start it again, because Steam overwrites `shortcuts.vdf` on exit.
3. Add (name defaults to the launcher's folder name):
   `itt run add-game add "<launcher>" [--name "<Game>"]`
   - `--dry-run` previews; `--no-steam` / `--no-apollo` do one side only. Re-running updates in place (keeps Steam play time, Apollo uuid).
   - Apollo writes need admin: Ivan clicks Yes on one UAC prompt, then Apollo restarts (this ends any running stream).
4. Check the `note art:` line names the right game. If it's wrong, re-run with `--name` (the store title) or `--sgdb-id <id>` (from steamgriddb.com/game/<id>).
5. `itt run add-game list` shows both sides; `itt run add-game remove "<Game>"` removes the shortcut, its grid art and the Apollo entry.

What it sets up in Apollo: `virtual-display` (unless `APOLLO_VIRTUAL_DISPLAY=0`), so the game streams on its own screen. A launcher that self-elevates (`RunAs`, `net session`) gets `elevated` (override with `--admin` / `--no-admin`). For each service the script creates (`sc create`), Apollo gets an elevated undo step that stops and deletes it, because quitting from Moonlight kills the script before its own cleanup runs.

## Safety
- Kernel drivers a script installs are signature-checked; anything not validly signed stops the add (`PROBLEM ... not validly signed`). Tell Ivan the signer from the `note kernel driver` line either way.
- Never edit the game's own files or configs, and never install addons or mods unless Ivan asks.

## Fixes
- Game opens on the physical monitor while streaming: the virtual display isn't primary. Apollo needs `dd_configuration_option = ensure_primary` in `sunshine.conf`, and the SudoVDA and ViGEmBus drivers installed (Apollo's log says if either is missing).
- `steam: no logged-in Steam user`: Ivan logs in to Steam once, then re-run.
- Art missing in Steam after adding: restart Steam once; it caches the library view.
- SteamGridDB 403: the key is wrong or revoked. `sops -d "$SGDB_SECRET"` must decrypt (never print the key itself).
