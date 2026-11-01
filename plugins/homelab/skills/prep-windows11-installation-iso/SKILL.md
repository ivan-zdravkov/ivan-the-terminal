---
name: prep-windows11-installation-iso
description: Build a debloated, unattended Windows 11 install USB - latest official ISO, local account (no Microsoft account), ~50 preinstalled apps removed, chosen apps (browsers, Claude, launchers, media, dev tools) installed silently at first logon, SSH/age keys and Git restored. Use when Ivan installs or reinstalls Windows, wants a clean Windows USB, or asks to debloat a new install.
compatibility: Answer file and app payload build on Linux and Windows; writing the USB stick is Linux-only (udisks + wimlib, no sudo).
---

# Prepare a Windows 11 install USB

Replaces: Microsoft's account-first, ad-filled setup, Rufus/tiny11-style tweaking by hand, and an afternoon of installer clicking.
Config: `~/.config/ivan-the-terminal/prep-windows11-installation-iso.conf` (template: `config.example`; every key has a sane default).
Secrets: `WIN11_PASSWORD` and `WIN11_PRODUCT_KEY` come from the environment, e.g. `sops exec-env <overlay>/secrets/windows.enc.env '...'`. Never pass them as arguments.
Everything is built in `~/.local/state/ivan-the-terminal/prep-windows11-installation-iso/`. All commands: `itt run prep-windows11-installation-iso <cmd>`.

## Steps
1. `plan`: shows the account, locale, keyboards, removed apps, first-logon apps and key restore. Confirm them with Ivan. Ask for anything that changed:
   - username, and the password (stored with sops, never in the conf)
   - Home or Pro, and the product key (optional; without one it installs and activates later)
   - apps to add or drop. App names are in `references/apps.md`; any winget id works as `winget:<Id>`. `toolchain` installs everything ivan-the-terminal's doctor checks (`toolchain.txt`: Python, PowerShell 7, gh, sops, age, gitleaks, adb, ...).
2. `iso`: finds the newest Windows 11 ISO in `ISO_DIR` and prints its SHA-256. If there is none, the script prints the steps for Microsoft's page and Ivan downloads it in his browser. Microsoft blocks scripted downloads, so never try to get around that. Re-run `iso` when it's done.
3. `answer` (inside `sops exec-env`): writes `autounattend.xml`. Non-secret settings go to the generator site. The password and key are filled in locally afterwards.
4. `apps`: downloads every installer from its official source and verifies it. It checks the winget manifest SHA-256, the release digest, or Anthropic's checksum; fixed URLs fall back to the Authenticode publisher via `osslsigncode`. It then writes `install-apps.ps1` and `restore-keys.ps1`. A failure names the app; drop it or retry.
5. USB (Linux):
   - New stick: `lsblk`, confirm the device with Ivan (it gets erased), then `usb --device /dev/sdX --format --yes`.
   - Already-written stick: `usb` rewrites it; `usb --payload-only` only refreshes the answer file and installers, which takes seconds.
   - It refuses non-USB disks and verifies the copy and the split `install.wim`.
6. Tell Ivan:
   - boot the stick's UEFI entry with the external data drives unplugged
   - on the only screen left, the disk picker, delete the old partitions and pick the unallocated space
   - keep Ethernet in
   - at first logon two PowerShell windows run; the result lands in `Setup report.txt` on the desktop
   - delete `autounattend.xml` from the stick afterwards, because it holds the password and key

## After the install
- `restore-keys.ps1` copies `KEYS_VOLUME:\KEYS_DIR\ssh` to `~\.ssh` (owner-only ACL) and `age\keys.txt` to `%APPDATA%\sops\age\`. It turns on the OpenSSH agent and points Git at Windows OpenSSH with your name and email. If the drive was unplugged at first logon, plug it in and run `C:\Setup\Installers\restore-keys.ps1`.
- Then follow `new-machine`: `ssh-add`, `gh auth login`, clone ivan-the-terminal, `itt bootstrap` (with `toolchain` on the stick it only links things up).

## Fixes
- The generator site is down or has changed its form: read `references/answer-file.md`. You can pass any generator field with `GENERATOR_EXTRA`.
- An app hash mismatches and there's no `osslsigncode`: `brew install osslsigncode`, then run `apps` again.
- A launcher hangs the first-logon window: each installer gets 30 minutes, then the script moves on. Re-run `C:\Setup\Installers\install-apps.ps1` later.
- Setup still asks for a Microsoft account: the stick has an old answer file. Re-run `answer`, then `usb --payload-only`.

For the debloat profile and why each setting is there, read `references/answer-file.md`. For app sources, silent switches and how they're verified, read `references/apps.md`.
