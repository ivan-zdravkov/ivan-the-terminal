---
name: rom-sync
description: Mirror selected systems of the ROM library to a device - an Android tablet/handheld over adb, an SD card or any mounted path - copying only missing or changed files, optionally removing extras. Use when Ivan wants games on the tablet or a handheld, after the library changed, or asks what's out of sync.
---

# ROM sync

Targets come from `~/.config/ivan-the-terminal/retro.conf`: `TARGET_<name>` (`adb:/path` or a directory) and `TARGET_<name>_systems`.

1. `itt run rom-sync targets` lists the targets.
2. `itt run rom-sync plan <target> [system...]` shows per-system counts and GiB; `--details` lists the files.
3. Check free space on the device first (`adb shell df -h /sdcard`, or `df -h <dir>`), then tell Ivan the size.
4. `itt run rom-sync push <target> [system...]`. Add `--delete` only when Ivan wants extras on the device removed, for example after replacing GameCube games with their PS2 versions.
5. adb needs the device unlocked with USB debugging allowed; if it says no device, ask Ivan to check the prompt on the tablet. An MTP mount (gvfs path) works as a directory target but is slow, so prefer adb.

Emulator settings on the device (cores, resolution, shaders) aren't handled here; ask before changing them.
