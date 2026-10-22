# Remediation

## mount:* not mounted
1. `findmnt <target>` is empty. Check `systemctl status <unit>` and `journalctl -k -b | grep -i <fstype>`.
2. **Dirty NTFS** (`volume is dirty and "force" flag is not set`), after an unclean unplug, power loss or Windows Fast Startup. The user runs:
   `sudo ntfsfix -d <device>` then `sudo systemctl start <unit>`. `lsblk -f` shows the device.
   ntfsfix is a surface repair. If it recurs, run `chkdsk /f` from Windows. Don't add `force` to fstab permanently.
3. Wrong or missing UUID: compare `lsblk -f` with `/etc/fstab`.
4. With `nofail` nothing complains at boot: the mountpoint is just an empty directory, and apps say "files missing".

## os-reboot / auto-updates
- Atomic images stage the update and apply it on reboot. `rpm-ostree status` shows booted and staged.
- Roll back after a bad update: pick the previous entry in the boot menu, or `rpm-ostree rollback` (asks for auth).
- If uupd failed, `journalctl -u uupd -n 100` usually shows the cause: network, disk full or a broken flatpak remote.

## disk:*
Biggest wins first: `du -xh --max-depth=2 ~ | sort -h | tail -20`, `flatpak uninstall --unused`, `podman system prune`,
`brew cleanup`, `journalctl --user --vacuum-size=200M`, and old Proton/Wine prefixes and shader caches.
Never delete user data without asking. List candidates with sizes and let the user choose.

## smart:*
`failing` or NVMe `critical warning`: back up immediately, then run a long self-test
(`sudo smartctl -t long /dev/X`, results in `sudo smartctl -a /dev/X`). Bad sectors that keep growing mean the drive should be replaced.

## unit:* / watch:* / container:*
`journalctl [--user] -u <unit> -n 50 --no-pager`. Fix the cause, then `systemctl [--user] restart <unit>`.
A timer showing `last run failed` means its service failed: check the service's journal, not the timer's.
Container: `podman logs --tail 50 <name>`. Quadlet or systemd-managed containers restart through their unit.

## dns / internet / tailscale
- `resolvectl status`. With Tailscale MagicDNS, upstream DNS filtering (NextDNS and similar) can block domains. Check the filter's logs.
- `tailscale status`, `tailscale netcheck`. Re-auth with `tailscale up`. If a peer is offline, wake it or check its app.
