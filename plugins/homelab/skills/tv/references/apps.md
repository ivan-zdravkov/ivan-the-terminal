# TV apps: sources and choices

| key | package | official source | integrity |
|---|---|---|---|
| stremio | `com.stremio.one` | newest stable `-androidTV` build listed on stremio.com/downloads (dl.strem.io), per ABI | HTTPS only; Android enforces the same signer on update |
| stremio-boot | `com.stremio.tv.launcher` | Stremio's own "Launch on Boot" helper, dl.strem.io/android/StremioLaunchOnBoot.apk | unversioned: installed when missing, never auto-updated |
| smarttube | `org.smarttube.stable` | GitHub `yuliskov/SmartTube` latest non-prerelease, `SmartTube_stable_<ver>_<abi>.apk` | sha256 from the release asset digest |
| tailscale | `com.tailscale.ipn` | pkgs.tailscale.com/stable (`?mode=json` → universal APK) | sha256 from `<apk>.sha256` |

## Why these
- **SmartTube** is the community-standard ad-free YouTube client for Android TV: it blocks ads and SponsorBlock segments, plays up to 8K, and needs no root. It is open source and not on any app store. Copies on APK sites are fakes.
  The 2025 signing-key leak shipped malware in 30.43/30.47 under the old package. Clean builds use a new key and the new package `org.smarttube.stable`. If the old `com.teamsmart.videomanager.tv` is present, uninstall it.
- **Stremio Launch on Boot** listens for `BOOT_COMPLETED` and starts Stremio. It needs the `SYSTEM_ALERT_WINDOW` app-op to start activities from the background (Android 10+). It also needs one manual launch to leave the "stopped" state, which `setup` handles.
  Its activity also declares a HOME category, but the Google TV launcher stays the default. Pressing Home still opens Google TV.
- **Tailscale** with `always_on_vpn_app` starts at boot without a UI. When "Use Tailscale DNS" is on (the default), Android sends DNS to Tailscale's quad-100 resolver. Tailscale then resolves tailnet names itself and forwards everything else to the tailnet's global nameservers, for example NextDNS with device metadata.
  Lockdown stays off, so the TV still works when the tailnet is down.
  Don't also set Android Private DNS to strict: it would bypass MagicDNS.

## Useful adb
- Foreground app: `adb shell dumpsys activity activities | grep -m1 mResumedActivity`
- Screen: `adb exec-out screencap -p > tv.png`. Remote keys: `adb shell input keyevent KEYCODE_DPAD_CENTER|BACK|HOME`
- Cold boot test for autostart: `adb reboot` (ask first: it interrupts whoever is watching).
