# Plan format (`graphics.py apply <plan.json>`)

```json
{
  "game": "Call of Duty - Modern Warfare 4",
  "slug": "call-of-duty-modern-warfare-4",
  "tier": "action",
  "cap": 120,
  "edits": [
    {"file": "%LOCALAPPDATA%/Activision/Call of Duty/players/s.1.0.cod26.txt", "format": "cod",
     "set": {"VRS@0": "false", "AATechniquePreferredMP@0": "FSR AA"}},
    {"file": "%USERPROFILE%/Documents/Game/settings.ini", "format": "ini",
     "set": {"Display": {"VSync": "0"}, "": {"TopLevelKey": "1"}}},
    {"file": "C:/Program Files (x86)/World of Warcraft/_forever_/WTF/Config.wtf", "format": "wtf",
     "set": {"maxFPS": "120"}}
  ],
  "why": {"VRS@0": "VRS shades fire and hair at reduced rate: blocky"},
  "optiscaler": {"install": false, "set": {"Upscalers.Dx12Upscaler": "fsr31"}},
  "manual": ["In game: Hair Strands -> All Characters High (ini index unknown)"],
  "notes": "Sources: TechSpot optimisation guide 2026-05; PCGamingWiki."
}
```

- **`slug`:** the one `scan` prints. It names the backup folder and the saved plan
  (`~/.config/ivan-the-terminal/game-graphics/games/<slug>.json`).
- **Formats:**
  - `ini`: nested `{section: {key: value}}`, with `""` for keys before any section. Missing keys and sections are added.
  - `wtf`: WoW's `SET k "v"`. Missing keys are added.
  - `cod`: existing `Name@N` entries only, with values checked against the file's `one of` / range comment.
  - `forza`: `<option id>` or element `value` attributes, existing only.
  - `json`: dotted paths.
- **Paths:** `%VAR%`, `$VAR` and `~` expand. The file must already exist, be text, have a config extension and sit
  under a scanned game dir, Documents, Saved Games or AppData (never browser, credential or setup folders).
- **Behaviour:** nothing is written if any edit fails, or if the game is running. Every write is backed up first
  (`restore <slug>` undoes it). Re-applying the same plan is a no-op.
- **What `apply` itself uses:** `game`, `slug` and `edits`. The other fields are for the report and the next run.
  Put everything that needs Ivan's hands in `manual`, one line each: menu-only settings, unverified encodings,
  Adrenalin clicks, BIOS.
- **OptiScaler:** a separate command, not part of `apply`:
  `optiscaler install <dir> --set Upscalers.Dx12Upscaler=fsr31 --set FSR.Fsr4Preset=1`.
