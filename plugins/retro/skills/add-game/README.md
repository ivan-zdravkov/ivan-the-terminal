# add-game

Point it at a game's launcher and the game shows up in **Steam** (as a non-Steam game) and in **Apollo / Sunshine** (for Moonlight streaming), both with proper art.

```text
itt run add-game add "C:\Games\Some Game\game.exe"
```

Replaces: Steam's "Add a Non-Steam Game" dialog, Steam ROM Manager, browsing SteamGridDB by hand, and hand-editing Apollo's `apps.json`.

## What it does

| Where | What gets written |
|---|---|
| Steam (every logged-in user) | a shortcut in `userdata/<id>/config/shortcuts.vdf`, and art in `config/grid/`: portrait cover, wide banner, hero background, logo and icon |
| Apollo / Sunshine | an app in `config/apps.json` with a PNG cover in `config/covers/`, then a service restart |

- **Art.** With a SteamGridDB key it fetches all five Steam art types from [SteamGridDB](https://www.steamgriddb.com). Without one it uses the game's official Steam store art (cover, banner, hero; the store API has no logos or icons). Apollo needs a PNG cover. It uses SteamGridDB's when there is one, else IGDB's via [LizardByte GameDB](https://github.com/LizardByte/GameDB), the source Apollo's own cover finder uses.
- **Name matching.** The name defaults to the launcher's folder name (`C:\Games\Forza Horizon 6\...` → "Forza Horizon 6"). Folder names abbreviate, so results are scored by the name's significant words, and the search is retried without short words: "AC Black Flag Resynced" finds *Assassin's Creed Black Flag Resynced*, not *AC/DC Live*. Sequel numbers must match. When nothing matches well it stops before writing anything.
- **Streaming on its own screen.** Apollo apps get `virtual-display`, so a stream gets a virtual monitor at the client's resolution and refresh rate, and your desktop stays untouched.
- **Launch scripts.** `.bat`/`.cmd` launchers run through `cmd /c`. A script that elevates itself (`RunAs`, `net session`) is set to run as admin in Apollo, so no UAC prompt lands on the stream. When a script creates a Windows service (`sc create`, e.g. an anti-cheat driver), Apollo gets an elevated undo step that stops and deletes it. Quitting from Moonlight kills the script before its own cleanup runs.
- **Safe to re-run.** Entries are matched by name and updated in place: Steam keeps play time, tags and the shortcut id (so art stays attached), and Apollo keeps the app's uuid. Shortcuts you added any other way are left alone, and `shortcuts.vdf` and `apps.json` are backed up (`.bak`) before each write.

## Setup

1. Log in to Steam once on the machine. Shortcuts are stored per Steam account.
2. Optional: a free SteamGridDB API key (steamgriddb.com → Preferences → API). Store it encrypted, e.g. with sops as a dotenv file holding `STEAMGRIDDB_API_KEY=...`, and point `SGDB_SECRET` at it. The script decrypts it in memory with `sops -d`, so it never lands on disk, in arguments or in output. `STEAMGRIDDB_API_KEY` in the environment works too.
3. Optional: `~/.config/ivan-the-terminal/add-game.conf` from [config.example](config.example). The defaults fit a stock Windows install of Steam and Apollo.

For streaming, Apollo itself needs its two drivers and the primary-display setting (see [Troubleshooting](#troubleshooting)).

## Usage

```text
itt run add-game add "<launcher>" [--name "<Title>"] [--args "<arguments>"] [--sgdb-id <id>]
                                  [--admin | --no-admin] [--no-steam] [--no-apollo] [--dry-run]
itt run add-game add --batch games.json [--no-steam] [--no-apollo] [--dry-run]
itt run add-game list
itt run add-game order [--dry-run]
itt run add-game display-index do|undo "<game.ini>" [--key DisplayIndex]
itt run add-game remove "<Title>" [--no-steam] [--no-apollo] [--dry-run]
```

| Option | Use it when |
|---|---|
| `--name` | the folder name isn't the game's title, or you want a different display name |
| `--args` | the launcher needs arguments, e.g. an emulator and its ROM: `add "C:\Emulators\eden\eden.exe" --args '-f -g "D:\roms\switch\Game.nsp"' --name "Game"`. They go into Steam's launch options and Apollo's command. Needs `--name`. |
| `--batch` | you add several games: a JSON list of `{"launcher", "name", "args", "sgdb_id", "admin", "prep"}` (`prep`: extra Apollo prep-cmds, `[{"do", "undo", "elevated"}]`). Steam restarts once and Apollo needs one UAC prompt for the whole list. The [emulators](../emulators/README.md) skill uses this. |
| `--sgdb-id` | the art is for the wrong game; take the id from `steamgriddb.com/game/<id>` |
| `--admin` / `--no-admin` | the admin detection for scripts got it wrong |
| `--no-steam` / `--no-apollo` | you want the game on one side only |
| `--dry-run` | you want to see the match and the plan without writing anything |

Output is problems plus one summary line, e.g.:

```text
note art: SteamGridDB 'Forza Horizon 6' (id 5503911): banner, hero, icon, logo, portrait
note apollo: added
Forza Horizon 6: steam=ok apollo=ok cover=SteamGridDB
```

What happens while it runs:
- **Steam restarts.** Steam rewrites `shortcuts.vdf` when it exits, so a running Steam is closed (`steam -shutdown`), the file is written, and Steam is started again. Don't run it mid-game.
- **One UAC prompt on Windows.** Apollo's config lives under Program Files, so the write and the service restart run elevated. Restarting Apollo ends any active stream.

### Grouping the Moonlight list

Apollo has no folders, but it serves apps in `apps.json` order, and Moonlight shows that order when Apollo's `legacy_ordering = enabled` is set (Artemis always does). Set `APOLLO_ORDER`, e.g. `"pc switch ps3 xbox360 apps"`, and every write keeps the list grouped, alphabetical within each group. `order` re-sorts without adding anything.

| Group | Apps |
|---|---|
| a system (`switch`, `ps3`, `xbox360`, `ps2`, `3ds`, ...) | commands that start a known emulator (Eden/Ryujinx, RPCS3, Xenia, PCSX2, Azahar, ...) |
| `apps` | Apollo's own entries: Desktop and Steam (no command, or a Steam URL) |
| `pc` | everything else |

Groups not in `APOLLO_ORDER` come just before `apps`. Apollo's built-in Virtual Desktop entry isn't in `apps.json`, so it stays where Apollo puts it.

### Games that pick their monitor by number

Most games open on the primary display, which Apollo switches to its virtual display during a stream (`ensure_primary`). A few save a monitor *number* in their settings instead (e.g. `DisplayIndex=0` in Assassin's Creed Black Flag Resynced's ini) and open on a physical monitor. For those, add an Apollo prep-cmd through `--batch`:

```json
[{"launcher": "C:\\Games\\Game\\Game.exe", "name": "Game",
  "prep": [{"do": "\"<python.exe>\" -I \"<addgame.py>\" display-index do \"<game.ini>\"",
            "undo": "\"<python.exe>\" -I \"<addgame.py>\" display-index undo \"<game.ini>\""}]}]
```

`do` writes the primary display's number, in Windows display order, into the ini and keeps your value. `undo` puts your value back after the stream, so the game still opens on your monitor at the desk. Use the real `python.exe` path (`python -c "import sys; print(sys.executable)"`), not the Microsoft Store alias.

## Safety

- **Read a launch script before adding it.** It runs as you, and as admin if it elevates itself.
- **Kernel drivers are checked.** Drivers a script loads (`sc create ... type= kernel`) are Authenticode-checked. A driver that isn't validly signed stops the add, and the signer is always shown. The exe a script starts is checked and reported too.
- **No game changes.** It never changes the game's own files, settings or mods.

## Troubleshooting

| Symptom | Fix |
|---|---|
| The stream shows your desktop, or the game opens on your physical monitor | Apollo's virtual display driver (SudoVDA) or controller driver (ViGEmBus) is missing; Apollo's `sunshine.log` says which. Also set `dd_configuration_option = ensure_primary` in `sunshine.conf`, so the virtual display becomes primary and games open on it. |
| The virtual display is primary, but one game still opens on a physical monitor | the game saved a monitor number; see [Games that pick their monitor by number](#games-that-pick-their-monitor-by-number) |
| Apollo logs `Failed to launch process: 740` | the exe demands admin; re-run with `--admin` (Apollo `elevated`) |
| Moonlight ignores the app order | set `legacy_ordering = enabled` in Apollo's `sunshine.conf`, check the client's "legacy ordering" toggle in Apollo's client list, then refresh the app list on the client |
| `no confident art match` | re-run with `--name "<store title>"` or `--sgdb-id <id>` |
| `steam: no logged-in Steam user yet` | log in to Steam once, then re-run |
| Art doesn't show in Steam | restart Steam once; it caches the library view |
| `the elevated step didn't finish` | the UAC prompt was declined or timed out; nothing in Apollo was changed, so re-run |
| SteamGridDB errors (403) | the key is wrong or revoked; check that `sops -d` decrypts the secret |

## Platforms

The Steam part runs on Windows and Linux. The Apollo part writes Apollo's Windows config (elevated). On Linux it writes a user-owned Sunshine config, and you restart Sunshine yourself. CI runs the tests on both.
