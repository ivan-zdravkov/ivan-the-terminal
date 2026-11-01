# TV apps: sources and choices

| key | package | official source | integrity |
|---|---|---|---|
| stremio | `com.stremio.one` | newest stable `-androidTV` build listed on stremio.com/downloads (dl.strem.io), per ABI | HTTPS only; Android enforces the same signer on update |
| stremio-boot | `com.stremio.tv.launcher` | Stremio's own "Launch on Boot" helper, dl.strem.io/android/StremioLaunchOnBoot.apk | unversioned: installed when missing, never auto-updated |
| smarttube | `org.smarttube.stable` | GitHub `yuliskov/SmartTube` latest non-prerelease, `SmartTube_stable_<ver>_<abi>.apk` | sha256 from the release asset digest |
| tailscale | `com.tailscale.ipn` | pkgs.tailscale.com/stable (`?mode=json` → universal APK) | sha256 from `<apk>.sha256` |
| keymapper | `io.github.sds100.keymapper` | GitHub `keymapperorg/KeyMapper` latest release, `keymapper-<ver>-foss.apk` (GPL, no Play services) | sha256 from the release asset digest |

## Why these
- **SmartTube** is the community-standard ad-free YouTube client for Android TV: it blocks ads and SponsorBlock segments, plays up to 8K, and needs no root. It is open source and not on any app store. Copies on APK sites are fakes.
  The 2025 signing-key leak shipped malware in 30.43/30.47 under the old package. Clean builds use a new key and the new package `org.smarttube.stable`. If the old `com.teamsmart.videomanager.tv` is present, uninstall it.
- **Stremio Launch on Boot** listens for `BOOT_COMPLETED` and starts Stremio. It needs the `SYSTEM_ALERT_WINDOW` app-op to start activities from the background (Android 10+). It also needs one manual launch to leave the "stopped" state, which `setup` handles.
  Its activity also declares a HOME category, but the Google TV launcher stays the default. Pressing Home still opens Google TV.
- **Tailscale** with `always_on_vpn_app` starts at boot without a UI. When "Use Tailscale DNS" is on (the default), Android sends DNS to Tailscale's quad-100 resolver. Tailscale then resolves tailnet names itself and forwards everything else to the tailnet's global nameservers, for example NextDNS with device metadata.
  Lockdown stays off, so the TV still works when the tailnet is down.
  Don't also set Android Private DNS to strict: it would bypass MagicDNS.

## Remote app buttons (Key Mapper)
- On many Android TVs the remote's app buttons are Android "global keys": the window manager hands them to a vendor service, which launches the app before any accessibility service sees the key. Button Mapper and Key Mapper's normal mode can't catch them. Several buttons can also share one Android keycode (on some TVs, YouTube, Disney+ and Prime all send the same keycode), so remapping must tell them apart by evdev scan code.
- Key Mapper's **Expert Mode** runs a bridge as the adb shell user that grabs the IR input device (`getevent -lp` lists it), handles mapped scan codes and re-injects every other key. `setup` enables the accessibility service, grants WRITE_SECURE_SETTINGS and the overlay app-op, and starts the bridge through the app's `start.sh` with the current APK paths.
- One-time, in the app: Settings > Expert Mode > start it once (this writes `start.sh`). For each button: New key map > Add action > Launch app, then record the trigger with the lightning (Expert) switch on, so the button reads "Record with Expert Mode". Press the button only while it says "Press your keys". Triggers show as `Scan code N (Expert • <ir device>)`. Then Export all and keep the backup in the private overlay.
- The bridge dies on reboot. Key Mapper's own "Auto start and keep alive" needs Wireless debugging paired inside the app. Some TVs only keep `adb_wifi_enabled` on after the TV's own "allow on this network" prompt. Until it's paired, `tv-bridge.timer` restarts the bridge from the PC.
- Remote keys that seem dead after a bridge crash come back when it restarts. Holding the power button is Key Mapper's emergency stop for the bridge.

## Useful adb
- Raw remote events (which scan code a button sends): `adb shell 'timeout 30 getevent -lt /dev/input/eventN > /data/local/tmp/ev.txt'`, then `cat` it. Output written straight to adb is buffered.
- Foreground app: `adb shell dumpsys activity activities | grep -m1 mResumedActivity`
- Screen: `adb exec-out screencap -p > tv.png`. Remote keys: `adb shell input keyevent KEYCODE_DPAD_CENTER|BACK|HOME`
- Cold boot test for autostart: `adb reboot` (ask first: it interrupts whoever is watching).
