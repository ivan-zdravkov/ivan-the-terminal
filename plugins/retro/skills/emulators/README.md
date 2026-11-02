# emulators

One emulation folder holds your ROMs, BIOS files, mods, patches and saves. This skill installs the best current emulator for Xbox 360, PS3 and Switch, points each one at that folder, sets them to upscale to 1440p and use 60 fps patches, and adds your chosen games to Steam and Apollo (Moonlight) with art.

```text
itt run emulators install        # Xenia Canary, RPCS3, Eden: latest official Windows builds
itt run emulators setup          # saves, keys + firmware, resolution, patches, mods
itt run emulators games          # GAME= lines -> Steam + Apollo shortcuts (via add-game)
```

Replaces: EmuDeck/RetroBat-style installers, Steam ROM Manager, and configuring three emulators by hand on every new PC.

## The emulation folder

Set `EMULATION_ROOT` in `~/.config/ivan-the-terminal/emulators.conf`. Everything below lives there, so reinstalling Windows or an emulator never touches it.

| Path | Holds | Used by |
|---|---|---|
| `roms/xbox360/` | disc images (`.iso`, `.xex` folders) | Xenia |
| `roms/ps3/<Game>/` | disc folders (`PS3_GAME/PARAM.SFO`, `USRDIR/EBOOT.BIN`) | RPCS3 (also listed in its game list) |
| `roms/switch/` | base games plus their update and DLC `.nsp` files side by side | Eden (game directory; updates/DLC load without installing) |
| `bios/**/PS3UPDAT.PUP` | PS3 system software | RPCS3 `--installfw` |
| `bios/**/prod.keys`, `title.keys`, `Firmware*.zip` | Switch keys and firmware (newest zip wins) | Eden `keys/`, `nand/system/Contents/registered/` |
| `mods/switch/<Game> [<TitleID>][mods]/<Mod>/` | Switch exefs/romfs mods, e.g. from the [Switch-Emulator-Ultrawide-FPS-Mods](https://github.com/Fl4sh9174/Switch-Emulator-Ultrawide-FPS-Mods) (unzip a game's zip there) | copied to Eden `load/<TitleID>/` |
| `saves/xbox360/` | Xenia content: `<XUID>/<TitleID>/...` + profiles | Xenia `content_root` |
| `saves/ps3/` | RPCS3 `savedata` folders (`<serial>...`) | junction from `rpcs3/dev_hdd0/home/00000001/savedata` |
| `saves/switch/` | Switch NAND `user/save`: `0000000000000000/<profile UUID>/<TitleID>/` | junction from `%APPDATA%\eden\nand\user\save` |

Emulators install to `EMU_DIR` (default `C:\Emulators`): `xenia-canary\` (portable: config and shader cache next to the exe), `rpcs3\` (always portable) and `eden\` (its data is in `%APPDATA%\eden`).

## What setup does

| Emulator | Settings |
|---|---|
| **Xenia Canary** (Xbox 360) | `draw_resolution_scale` = `RES_SCALE` (2 → 720p becomes 1440p), fullscreen, vsync, 60 fps cap, `apply_patches`, signs in the profile found in `saves/xbox360`, enables `XENIA_PATCH_<titleid>` patches from the bundled [game-patches](https://github.com/xenia-canary/game-patches) |
| **RPCS3** (PS3) | Vulkan, resolution scale `RES_SCALE`×100 %, 16× anisotropic, frame limit Auto, fullscreen, auto-exit when the game closes (Steam/Apollo see the end), disc folders in the game list, official patch database with `RPCS3_PATCH_<serial>` patches turned on |
| **Eden** (Switch) | docked mode, resolution `SWITCH_RES_SCALE` (1.5 → 1080p becomes 1620p, downsampled to 1440p), ROM folder as game directory, keys + firmware, the profile UUID that owns `saves/switch` (so old saves appear), chosen mods |

Config files are edited key by key, so anything else you change in an emulator's own UI stays. Each file is backed up once as `*.itt-bak` before the first change.

### Patches and mods

- **Switch mods** are chosen by folder name: `SWITCH_MODS` (default: 60 FPS, stabilize, 1080p, no dynamic resolution, better LOD) minus `SWITCH_MODS_SKIP` (ultrawide, 120 FPS, ...). Mods the skill installed and you later deselect are removed again; mods you added yourself are left alone.
- A mod only applies to the game version in its `exefs/<version>.pchtxt`. Check that it matches the installed update.
- Some "60 FPS" patches make the game run faster instead of smoother, because the game ties speed to frame rate. The patch notes usually say so.

## Games in Steam and Apollo

```text
GAME="xbox360|Some Game (USA).iso|Some Game"
GAME="ps3|Some Collection|Some Collection"
GAME="switch|Some Game [0100000000000000][v0].nsp|Some Game|<optional steamgriddb id>"
```

`games` builds the command line for each emulator (Eden `-f -g <rom>`, RPCS3 `--no-gui <EBOOT.BIN>`, Xenia `<iso>`) and hands the list to [add-game](../add-game/README.md) in one batch: one Steam restart and one UAC prompt, SteamGridDB art, Apollo virtual display. `--dry-run` shows the art matches first. The name is what Steam shows and what the art search uses, so prefer the store title.

## Safety

- **Downloads** come from each project's official releases: Xenia Canary's GitHub releases, RPCS3's `rpcs3-binaries-win` (checked against its `.sha256`), and Eden's own Forgejo (`git.eden-emu.dev`). Zip entries with absolute or `..` paths are refused.
- **Saves are never moved or overwritten.** If an emulator's save folder already holds data, setup stops and tells you to merge it into `saves/` yourself.
- **No game files are touched.** The ROM folder is only read.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `PS3 firmware not installed` | run the printed `rpcs3.exe --installfw "...PS3UPDAT.PUP"` once |
| Eden asks for a user, or a game shows no saves | the save folder must contain exactly one profile UUID, or set `SWITCH_PROFILE` |
| `already holds data` | the emulator has saves outside the library: copy them into `saves/<system>/`, delete the old folder, re-run setup |
| A 60 fps mod does nothing | the mod is for another game version; see its `.pchtxt` file names |
| Game runs at double speed | the 60 fps patch ties game speed to frame rate; take it out of the config and re-run setup |
| Steam art wrong | set the SteamGridDB id as the fourth `GAME=` field |
