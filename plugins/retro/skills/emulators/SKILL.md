---
name: emulators
description: Install, update and configure the Xbox 360 (Xenia Canary), PS3 (RPCS3) and Switch (Eden) emulators around one emulation folder - saves kept there, BIOS/keys/firmware, 1440p upscaling, 60 fps patches and mods - and add games to Steam + Apollo. Use when Ivan sets up or updates emulators, asks where emulator saves/ROMs live, or wants a console game in Steam or Moonlight.
compatibility: Windows (official Windows builds, junctions, Apollo). Config and tests are portable Python.
---

# Emulators

Replaces: EmuDeck / RetroBat-style installers and Steam ROM Manager; hand-editing three emulators' configs.
Config: `~/.config/ivan-the-terminal/emulators.conf` (template: `config.example`). The emulation folder is the source of truth; emulators only point at it, so a reinstall never touches ROMs or saves.

1. Update or install the emulators (latest official release, verified where a checksum is published; settings kept):
   `itt run emulators install [xenia rpcs3 eden]`
2. Wire them to the emulation folder (safe to re-run after any change to the config or the folder):
   `itt run emulators setup [xenia rpcs3 eden]`
   - Saves: Xenia `content_root` → `saves/xbox360`; RPCS3 `dev_hdd0/home/00000001/savedata` and Eden `nand/user/save` are junctions to `saves/ps3` and `saves/switch`. A folder that already holds saves is never replaced: setup stops with a PROBLEM; merge it into the library by hand, with Ivan.
   - Eden gets the profile UUID that owns `saves/switch`, so old saves show up. Updates and DLC next to the ROMs load without installing.
   - Mods: folders in `mods/switch/<Game> [<TitleID>][mods]/` matching `SWITCH_MODS` (and not `SWITCH_MODS_SKIP`) are copied to Eden's `load/`. Patches: `XENIA_PATCH_<titleid>` / `RPCS3_PATCH_<serial>` regexes.
3. Fix each `PROBLEM`. The PS3 firmware needs RPCS3 to run once; hand Ivan the exact `--installfw` command from the output.
4. Add games to Steam + Apollo: add `GAME="<system>|<rom or PS3 folder>|<name>"` lines to the config, then
   `itt run emulators games --dry-run` (check every `note art:` names the right game), then without `--dry-run`.
   One Steam restart and one UAC prompt for the whole batch; ask first if Ivan might be playing or streaming.
5. `itt run emulators status` shows versions and save links; `itt run emulators command "<rom>"` prints a launch line.

For the folder layout, what each setting does and why, read `README.md`.

## Rules
- Never move, merge or delete saves without Ivan's go-ahead; back up `saves/` first if a merge is needed.
- Skip ultrawide mods (16:9 monitors). A mod made for another game version silently does nothing: compare its `exefs/<version>.pchtxt` with the installed update.
- Avoid games that have a better PC port on Steam; ask before assuming a console exclusive has none.
- Don't run the downloaded emulators headlessly from the session; ask Ivan to launch one when a first run is needed.

## Fixes
- Switch game asks to create a user, or saves are missing: `status`/`setup` again; several UUIDs in `saves/switch` need `SWITCH_PROFILE`.
- `keys`/firmware errors in Eden: `prod.keys`, `title.keys` and a `Firmware*.zip` must be under `bios/`; re-run setup after replacing them.
- Game too fast/slow after a 60 fps patch: the patch ties game speed to frame rate; turn it off in the config (`SWITCH_MODS`, `*_PATCH_*`) and re-run setup.
- Stream shows the desktop: see add-game's Fixes (Apollo virtual display + `ensure_primary`).
