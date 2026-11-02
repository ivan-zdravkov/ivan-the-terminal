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
| `roms/switch/` | base games plus their update and DLC `.nsp` files side by side | Eden (game directory; DLC loads from here, updates must be installed to NAND once) |
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
| **Eden** (Switch) | docked mode, resolution `SWITCH_RES_SCALE` (1.5 → 1080p becomes 1620p, downsampled to 1440p), ROM folder as game directory, keys + firmware, the profile UUID that owns `saves/switch` (so old saves appear), chosen mods; flags updates of your `GAME=` Switch games that aren't installed yet |

### Switch updates

Eden reads DLC straight from the ROM folder, but from an update it only takes the data (RomFS), not the code (ExeFS). The game then runs its original code on the update's data and crashes or hangs on a black or blue screen. So install each update once: in Eden, **File → Install Files to NAND** and pick the update `.nsp` files (several at once is fine). That copies them to `%APPDATA%\eden\nand\user\Contents`; saves aren't touched. `setup` lists the ones still missing. In the log, a mod's `.pchtxt` that matches the base version (e.g. `1.0.0.pchtxt` applied on an updated game) means the update's code isn't loaded.

Config files are edited key by key, so anything else you change in an emulator's own UI stays. Each file is backed up once as `*.itt-bak` before the first change.

### Patches and mods

- **Switch mods** are chosen by folder name: `SWITCH_MODS` (default: 60 FPS, stabilize, 1080p, no dynamic resolution, better LOD) minus `SWITCH_MODS_SKIP` (ultrawide, 120 FPS, ...). Mods the skill installed and you later deselect are removed again; mods you added yourself are left alone.
- A mod only applies to the game version in its `exefs/<version>.pchtxt`. Check that it matches the installed update.
- Some "60 FPS" patches make the game run faster instead of smoother, because the game ties speed to frame rate. The patch notes usually say so.

## Controllers

Made for Xbox-style pads (XInput), which is also what Moonlight's virtual pad is through Apollo.

| Emulator | Player 1 |
|---|---|
| Xenia | any XInput pad, nothing to set |
| RPCS3 | `XInput Pad #1`, RPCS3's XInput layout: A = ✕, B = ○, X = □, Y = △, Guide = PS |
| Eden | Pro Controller, buttons **by position**: bottom = B, right = A, left = Y, top = X (the Xbox labels differ, the feel is a Switch pad) |

Eden binds a pad by its SDL GUID, and your physical pad and Moonlight's virtual Xbox 360 pad have different ones. So Switch games in Apollo run `emulators pad stream` before the stream and `emulators pad desk` after it. `itt run emulators pads` lists connected pads with the GUID Eden sees; set `SWITCH_PAD` so the desk pad is known even when it's switched off.

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
| Switch game crashes after a few seconds, or hangs on a black/blue screen while music plays | its update isn't installed to NAND (see Switch updates); `setup eden` names it |
| `Install Files to NAND` says one file failed | try that file again on its own; check it with `setup eden` afterwards |
| Pokemon Let's Go stuck on "Press a button on the controller you want to use" | it doesn't accept a Pro Controller when docked: add its title id to `SWITCH_HANDHELD` (handheld mode, button throws, 2× = 1440p) and re-run `setup eden` with Eden closed |
| Switch game doesn't react to the pad | at the desk: `emulators pad desk`. While streaming: run `emulators pads`; if Moonlight's pad shows another GUID, put it in `SWITCH_PAD_STREAM` and re-run `emulators games switch` |
| Over Moonlight a PS3 or Switch game ignores the pad (Xbox 360 games work) | Apollo made a DualShock 4 (its log: `Gamepad 0 will be DualShock 4 controller`), which isn't XInput. Set `gamepad = x360` in Apollo's `sunshine.conf` (the prep-windows11 skill's Apollo step does) and restart Apollo |
| PS3 game listens to the wrong pad | RPCS3 uses the first XInput slot; switch the other pad off |
