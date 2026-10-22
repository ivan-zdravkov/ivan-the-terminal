---
name: rom-library
description: Audit and tidy the emulation ROM library - formats to convert (disc images or zipped ISOs to CHD/RVZ), multi-disc sets missing .m3u, 50 Hz Europe-only titles to swap for 60 Hz, duplicates, junk and stub files, non-standard names, outdated Switch updates. Use when Ivan adds or downloads games, asks what's missing or wrong in the library, wants smaller files, or wants playlists fixed.
---

# ROM library

Library root and region preference come from `~/.config/ivan-the-terminal/retro.conf` (template: `config.example`). If the root is missing, the drive is probably unmounted: run the homelab-check skill first.

1. `itt run rom-library audit [system...]` prints one line per system. Add `--details` to list every issue, `--json` for machine-readable output.
2. Fixes are dry runs until you add `--apply`. Show Ivan the plan, then apply what he approves:
   - `convert <system>` turns `.cue`/`.iso`/`.gdi` or zipped single images into CHD (PSX/PS2/PSP/...), and `.iso`/`.wbfs` into RVZ (GC/Wii). Each output is verified. `--limit N` runs a test batch. `--delete-source` removes the originals; only use it after Ivan agrees.
   - `m3u <system>` moves discs into `<Title>/` (with `noload.txt`) and writes `<Title>.m3u` next to it.
3. Judgement calls are Ivan's. Present them as a short list and never delete anything yourself:
   - `pal-only (50Hz)`: suggest the USA/World release, especially for consoles where 60 Hz matters to him.
   - `duplicate-title`: keep the preferred region / best format.
   - `junk`, `switch-stub` (<50 KB), `switch-old-update`: list them, and delete only after he confirms.
   - `no-region-tag`: often hacks or translations; just mention them.
4. After changing the library, offer to sync devices with the rom-sync skill.

Dual-format users: if a game has a PS2 version, Ivan often prefers it over the GameCube one, but keep both when he says so.
