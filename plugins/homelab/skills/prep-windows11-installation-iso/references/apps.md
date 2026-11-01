# First-logon apps

Each installer is downloaded on the prep machine, verified, copied to the stick as `$OEM$\$1\Setup\Installers\`, which Setup copies to `C:\Setup\Installers\`, and run silently by `install-apps.ps1` at first logon. Nothing is fetched from a mirror or a third-party repack.

| Name in `APPS` | App | Source | Verified by | Silent install |
| --- | --- | --- | --- | --- |
| `git` | Git for Windows | winget `Git.Git` (GitHub release) | winget SHA-256 | Inno `/SP- /VERYSILENT /SUPPRESSMSGBOXES /NORESTART` |
| `vscode` | Visual Studio Code (system installer) | winget `Microsoft.VisualStudioCode` | winget SHA-256 | Inno + `/mergetasks=!runcode` |
| `brave` | Brave | GitHub `brave/brave-browser` latest, `BraveBrowserStandaloneSilentSetup.exe` | release asset digest | silent by design |
| `claude` | Claude desktop | `claude.ai/api/desktop/win32/x64/msix/latest/redirect` | MSIX signature present, publisher Anthropic, PBC (Windows checks the signature on install) | `Add-AppxPackage` |
| `claude-code` | Claude Code | `downloads.claude.ai/claude-code-releases` (what `install.ps1` uses) | release manifest SHA-256 | `claude.exe install` |
| `steam` | Steam | winget `Valve.Steam` | winget SHA-256, else Authenticode "Valve" | NSIS `/S` |
| `battlenet` | Battle.net | winget `Blizzard.BattleNet` | winget SHA-256, else Authenticode "Blizzard" | `--lang=enUS --installpath=...` (progress window, no prompts) |
| `ea` | EA app | winget `ElectronicArts.EADesktop` | winget SHA-256, else Authenticode "Electronic Arts" | Burn `/passive /norestart` |
| `epic` | Epic Games Launcher | winget `EpicGames.EpicGamesLauncher` (MSI) | winget SHA-256, else Authenticode "Epic Games" | `msiexec /i ... /quiet /norestart` |
| `ubisoft` | Ubisoft Connect | winget `Ubisoft.Connect` | winget SHA-256, else Authenticode "Ubisoft" | NSIS `/S` |
| `gog` | GOG Galaxy | winget `GOG.Galaxy` | winget SHA-256, else Authenticode "GOG" | Inno silent |
| `7zip` | 7-Zip | winget `7zip.7zip` | winget SHA-256 (unsigned; checked again on the target) | NSIS `/S` |
| `qbittorrent` | qBittorrent | winget `qBittorrent.qBittorrent` (SourceForge release) | winget SHA-256 (unsigned; checked again on the target) | NSIS `/S` |
| `stremio` | Stremio | winget `Stremio.Stremio` (`dl.strem.io`) | winget SHA-256, Authenticode "Smart Code" | NSIS `/S` |
| `potplayer` | PotPlayer | winget `Daum.PotPlayer` (fixed "Latest" URL) | winget SHA-256, else Authenticode "Kakao Corp" | NSIS `/S` |
| `toolchain` | every `toolchain.txt` tool with a winget id (Python, PowerShell 7, gh, jq, gitleaks, sops, age, shellcheck, adb, 7-Zip, MAME's chdman) | winget manifests | winget SHA-256, checked again on the target | MSI/MSIX as usual; zip and portable tools unpack to `%LOCALAPPDATA%\Programs\ivan-the-terminal` and go on the user PATH |
| `winget:<Id>` | any winget package | winget manifest | winget SHA-256 only | the manifest's switches, else the installer type's default |

## How a winget app is resolved
1. The newest version folder under `manifests/<letter>/<Publisher>/<Package>/` in `microsoft/winget-pkgs`, using the GitHub API with `GITHUB_TOKEN` or `gh auth token` when available.
2. The installer: x64 machine-scope first, then neutral, then x86. Top-level fields are defaults for each installer.
3. Switches: the manifest's `Silent` (else the type's default: Inno, NSIS, MSI/WiX, Burn) plus `Custom`. When the manifest requires an install location, the default location fills `<INSTALLPATH>` and `%VARS%` are expanded on the target.

## Toolchain packages
- `toolchain` expands to one `toolchain:<command>` per row, after the named apps; a package already named (e.g. `git`) isn't installed twice.
- Unsigned installers (7-Zip, MAME, most portable tools) are checked on the target against the winget SHA-256 instead of Authenticode.
- `win-dir` in `toolchain.txt` goes on the user PATH, and is the install location when the installer requires one (MAME).
- `WINGET_EXTRAS` in `scripts/winprep.py`: PowerShell 7 uses its MSI, not the msixbundle; the Python Install Manager runs `py install --configure -y` afterwards to add the default runtime and its PATH entry.

## Fixed URLs
Steam, Ubisoft and Battle.net serve the newest build at the same URL, so the file can drift from the manifest's hash between winget updates. Such a file is accepted only if `osslsigncode` validates its Authenticode signature against the system CA bundle and the signer's subject contains the expected publisher. Without `osslsigncode` it fails and names the fix.

## At first logon
- Installers run one at a time. `Start-Process` + `WaitForExit` (not `-Wait`, which hangs on launchers that start their client) with a 30-minute cap each.
- The log is `C:\Setup\Installers\install-apps.log`, with a one-line-per-app summary in `Setup report.txt` on the desktop. Re-running `install-apps.ps1` is safe; installers upgrade in place.
- `restore-keys.ps1` runs last (see SKILL.md). It adds GitHub's published ed25519 host key to `known_hosts`, so the first `git clone` over SSH doesn't prompt.

## Adding an app to the catalog
Add an entry to `CATALOG` in `scripts/winprep.py` (`source: winget` + `id` + expected `signer` covers most apps), a row here, and a test if its switches are unusual.
