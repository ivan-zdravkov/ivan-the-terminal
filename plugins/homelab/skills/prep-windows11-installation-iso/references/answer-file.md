# The answer file (autounattend.xml)

Built with Christoph Schneegans' [unattend generator](https://schneegans.de/windows/unattend-generator/), the most thorough maintained one. It writes the setup scripts that remove apps and apply settings during Setup, so the debloat happens before first logon instead of in a cleanup tool afterwards.

## Privacy
- What goes to the site, as GET query parameters: language, keyboards, home location, time zone, computer name, account name, edition, the removal list and the settings below. That's the same as using its web form.
- What never goes there: the password and the product key. The request carries a placeholder password and Microsoft's public generic install key for the edition. `finalize_answer()` swaps in the obscured password (Base64 of UTF-16LE `password + "Password"`, which is what Setup expects; obscured, not encrypted) and the real key locally.
- The finished file still holds both, so it lives only in the state dir and on the stick. Setup deletes its own copies (`C:\Windows\Panther\unattend*.xml`) at first logon. Delete the one on the stick yourself.

## Local changes after generation
- `HideOnlineAccountScreens` is set to true. The account is local anyway; this also hides the Microsoft-account upsell.
- One more `FirstLogonCommands` entry runs `C:\Setup\Installers\install-apps.ps1`. If Setup didn't copy `$OEM$`, it first copies the folder from whichever drive holds `$OEM$\$1\Setup\Installers`, i.e. the stick.

## Setup flow
- Product key in `windowsPE`: it picks the edition, so there are no key or edition screens.
- Partitioning is **interactive**. This is the only screen left, on purpose, so the wrong disk is never wiped silently.
- `BypassNetworkCheck`: Setup works offline or online. Ethernet in is recommended so the first-logon installs can reach the network.
- One local administrator logs in automatically once (`AutoLogon` count 1), and the password never expires.

## Debloat profile (`BASE_SETTINGS` in `scripts/winprep.py`)
| Area | Setting |
| --- | --- |
| Privacy | Express settings: disable all (diagnostics, ad ID, location, tailored experiences) |
| Start / taskbar | Start pins emptied, taskbar pins emptied, search box hidden, Task View hidden, Widgets off, Bing web results in search off, app suggestions/"tips" off |
| Edge | First-run experience hidden, startup boost off, desktop icon removed, made uninstallable (Settings > Apps, EEA regions) |
| OEM | WPBT off (firmware can't inject vendor software such as motherboard utilities), device-specific apps not auto-installed |
| System | BitLocker auto device encryption prevented, Fast Startup off (it leaves NTFS disks "dirty" for other OSes), long paths on, Core Isolation left on |
| Explorer | File extensions shown, "End task" in the taskbar menu |
| Input | Sticky Keys shortcut off (Shift x5 in games), mouse acceleration (enhance pointer precision) off |

## Removed apps (default `REMOVE`)
3D Viewer, Bing Search, Camera, Clipchamp, Clock, Copilot, Cortana, Dev Home, Windows Hello face, Family, Feedback Hub, Game Assist, Get Help, handwriting, Internet Explorer, Mail and Calendar, Maps, Math Input Panel, Mixed Reality, Movies & TV, News, Office hub, OneDrive, OneNote, OneSync, Outlook, Paint 3D, People, Power Automate, PowerShell 2.0, PowerShell ISE, Quick Assist, Recall, Remote Desktop client, Skype, Solitaire, speech packs, Steps Recorder, Sticky Notes, Teams, Tips, To Do, Sound Recorder, Wallet, Weather, Windows Media Player (classic and new), WordPad, Xbox apps, Phone Link.

**Kept on purpose:**
- Microsoft Store, which updates App Installer and with it `winget`
- Media Features, because games need Media Foundation
- Calculator, Notepad, Paint, Photos, Snipping Tool, Terminal
- OpenSSH client, which Git and `restore-keys.ps1` use

Drop `XboxApps` from `REMOVE` for Game Pass or Xbox-network PC games, which need the Xbox Identity Provider. You can also reinstall it from the Store later.

## Tune-up after the apps (`scripts/tune-windows.ps1`)
Runs at the end of `install-apps.ps1`, when every app's shortcuts and Run entries exist, and on a live PC with `tune`. It's idempotent and only reports what it changed.

| Area | Setting |
| --- | --- |
| Taskbar | Alignment (`center`/`left`), auto-hide, every tray icon promoted (`alltray`). Clock/calendar (Win+N) and Quick Settings with volume (Win+A) stay at the right of the taskbar |
| Pins | `TASKBAR_PINS` written as a taskbar layout (`%ProgramFiles%\ivan-the-terminal\taskbar-layout.xml`, "Start Layout" policy, `PinListPlacement="Replace"`). Windows reapplies it only when the file changes, instantly on 26200+. `PinGeneration="1"` keeps an unpinned app unpinned |
| Autostart | Run entries matching `AUTOSTART_OFF` are marked Disabled, as Task Manager does. Their `StartupApproved` flag survives app updates that re-add the entry |
| Debloat | Edge uninstalled and blocked from reinstalling (EEA only; the WebView2 runtime stays), Windows Fax and Scan (printing untouched), Phone Link's CrossDevice host |
| Gaming | Hardware-accelerated GPU scheduling, Game Mode on, Game DVR background recording off, optimizations for windowed games, .NET Framework 3.5 |
| Logon task | `ivan-the-terminal desktop` runs elevated at logon and every 15 minutes, with no window (`conhost --headless`). It promotes new tray icons and disables launchers that re-registered themselves |

Not touched on purpose: Defender, UAC, Windows Update, the print spooler, SysMain, search indexing and the power plan. Balanced is what AMD and Intel recommend for current CPUs.

## Changing a setting
Any generator field can be passed with `GENERATOR_EXTRA="Field=Value ..."`, which overrides the profile. The field names are the form's `name` attributes, visible in the source-URL comment at the top of every generated file. If the site changes a field name, the generated file silently lacks that setting, so compare that comment after a generator update.
