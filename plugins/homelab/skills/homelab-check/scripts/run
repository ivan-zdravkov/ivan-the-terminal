#!/usr/bin/env bash
# homelab-check: one-pass health report for a Linux home machine (atomic Fedora / Bazzite friendly).
# Prints problems only as "LEVEL check detail" plus a summary line; exit 1 on any fail.
#   -v        show passing checks too
#   --json    machine-readable output
#   --notify  desktop notification on warn/fail (for the systemd timer)
# Config (optional): ~/.config/ivan-the-terminal/homelab.conf, see ../config.example
# shellcheck disable=SC2015  # `test && r ok || r warn` is safe: r() always succeeds
set -uo pipefail

DISK_WARN=90 DISK_FAIL=95 STAGED_WARN_DAYS=3
WATCH_USER_UNITS="" WATCH_SYSTEM_UNITS="" WATCH_CONTAINERS="" WATCH_PEERS="" SKIP=""
CONF="${XDG_CONFIG_HOME:-$HOME/.config}/ivan-the-terminal/homelab.conf"
# shellcheck source=/dev/null
[ -f "$CONF" ] && . "$CONF"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/ivan-the-terminal/homelab-check"

verbose=0 json=0 notify=0
for a in "$@"; do case "$a" in -v) verbose=1 ;; --json) json=1 ;; --notify) notify=1 ;; esac; done
out=()
r() { out+=("$1"$'\t'"$2"$'\t'"$3"); }
skip() { [[ " $SKIP " == *" $1 "* ]]; }
has() { command -v "$1" >/dev/null; }
auto_updates=0; systemctl is-enabled -q uupd.timer 2>/dev/null && auto_updates=1

# --- OS image (rpm-ostree)
if ! skip os && has rpm-ostree; then
  st=$(rpm-ostree status --json 2>/dev/null)
  booted=$(jq -r '.deployments[] | select(.booted) | .version' <<<"$st")
  staged=$(jq -r '.deployments[] | select(.staged) | .version' <<<"$st")
  if [ -n "$staged" ]; then
    built=$(jq -r '.deployments[] | select(.staged) | .timestamp' <<<"$st")
    days=$(( ($(date +%s) - built) / 86400 ))
    if [ "$days" -ge "$STAGED_WARN_DAYS" ]; then r warn os-reboot "$staged staged ${days}d ago (booted $booted): reboot to apply"
    else r ok os-reboot "$staged staged, reboot when convenient"; fi
  else
    r ok os-image "$booted"
  fi
  if [ $auto_updates = 1 ]; then
    res=$(systemctl show -p Result --value uupd.service)
    [ "$res" = success ] && r ok auto-updates "uupd" || r warn auto-updates "last uupd run: $res (journalctl -u uupd -n 50)"
  fi
fi

# --- app updates (uupd applies these automatically when enabled)
pending() {  # pending CHECK COUNT WHAT
  if [ "$2" -eq 0 ]; then r ok "$1" "current"
  elif [ $auto_updates = 1 ]; then r ok "$1" "$2 $3 pending (auto-updated)"
  else r warn "$1" "$2 $3 pending: itt run system-updates --apply"; fi
}
if ! skip flatpak && has flatpak; then
  pending flatpak "$(flatpak remote-ls --updates --columns=application 2>/dev/null | grep -c .)" apps
fi
if ! skip brew && has brew; then
  pending brew "$(HOMEBREW_NO_AUTO_UPDATE=1 brew outdated --quiet 2>/dev/null | grep -c .)" formulae
fi
if ! skip firmware && has fwupdmgr; then
  fw=$(timeout 30 fwupdmgr get-updates --json 2>/dev/null | jq -r '[.Devices[]?.Name] | join(", ")')
  [ -z "$fw" ] && r ok firmware "current" || r warn firmware "updates for: $fw (run: fwupdmgr update)"
fi

# --- storage: usage per filesystem, nofail mounts actually mounted, SMART
if ! skip disks; then
  # One line per filesystem; label it by the mount that holds $HOME when there is one (btrfs subvolumes repeat).
  declare -A pct_of label_of
  home=$(readlink -f "$HOME")
  while read -r src pct target; do
    dev=${src%%\[*}
    pct_of[$dev]=${pct%\%}
    if [ -z "${label_of[$dev]:-}" ] || [[ "$home/" == "$target/"* && ${#target} -gt 1 ]]; then label_of[$dev]=$target; fi
  done < <(df -x tmpfs -x devtmpfs -x overlay -x squashfs -x efivarfs -x fuse.portal --output=source,pcent,target 2>/dev/null | tail -n +2)
  for dev in "${!pct_of[@]}"; do
    p=${pct_of[$dev]} t=${label_of[$dev]}
    if [ "$p" -ge "$DISK_FAIL" ]; then r fail "disk:$t" "${p}% used"
    elif [ "$p" -ge "$DISK_WARN" ]; then r warn "disk:$t" "${p}% used"
    else r ok "disk:$t" "${p}% used"; fi
  done
fi
if ! skip mounts; then
  while read -r dev target fstype opts _; do
    case "$dev" in ''|'#'*) continue ;; esac
    [[ ",$opts," == *,nofail,* && ",$opts," != *,noauto,* && "$fstype" != swap ]] || continue
    if findmnt -rn "$target" >/dev/null; then r ok "mount:$target" ""; continue; fi
    unit=$(systemd-escape -p --suffix=mount "$target")
    hint="systemctl status $unit"
    if [[ "$fstype" == ntfs* ]] && journalctl -k -b --no-pager -q 2>/dev/null | grep -q 'volume is dirty'; then
      hint="dirty NTFS: sudo ntfsfix -d <device> && sudo systemctl start $unit"
    fi
    r fail "mount:$target" "not mounted ($hint)"
  done < /etc/fstab
fi
if ! skip smart && has busctl; then
  prop() { busctl --system get-property org.freedesktop.UDisks2 "$1" "$2" "$3" 2>/dev/null | cut -d' ' -f2-; }
  for obj in $(busctl --system --list tree org.freedesktop.UDisks2 2>/dev/null | grep '^/org/freedesktop/UDisks2/drives/'); do
    model=$(prop "$obj" org.freedesktop.UDisks2.Drive Model | tr -d '"'); model=${model:-drive}
    if failing=$(prop "$obj" org.freedesktop.UDisks2.Drive.Ata SmartFailing) && [ -n "$failing" ]; then
      bad=$(prop "$obj" org.freedesktop.UDisks2.Drive.Ata SmartNumBadSectors)
      if [ "$failing" = true ]; then r fail "smart:$model" "SMART predicts failure: back up now"
      elif [ "${bad:-0}" -gt 0 ]; then r warn "smart:$model" "$bad bad sectors"
      else r ok "smart:$model" ""; fi
    elif cw=$(prop "$obj" org.freedesktop.UDisks2.NVMe.Controller SmartCriticalWarning) && [ -n "$cw" ]; then
      [ "$cw" = 0 ] && r ok "smart:$model" "" || r fail "smart:$model" "NVMe critical warning: $cw"
    fi
  done
fi

# --- services: anything failed, plus explicitly watched units and containers
if ! skip services; then
  while read -r unit _; do [ -n "$unit" ] && r fail "unit:$unit" "failed: systemctl status $unit"; done \
    < <(systemctl --failed --plain --no-legend 2>/dev/null)
  while read -r unit _; do [ -n "$unit" ] && r fail "user-unit:$unit" "failed: systemctl --user status $unit"; done \
    < <(systemctl --user --failed --plain --no-legend 2>/dev/null)
  watch() {  # watch user|system UNIT
    local sc=() u=$2 svc
    [ "$1" = user ] && sc=(--user)
    if [[ "$u" == *.timer ]]; then
      svc="${u%.timer}.service"
      if ! systemctl "${sc[@]}" is-enabled -q "$u" 2>/dev/null; then r fail "watch:$u" "timer not enabled"
      elif [ "$(systemctl "${sc[@]}" show -p Result --value "$svc")" != success ]; then
        r warn "watch:$u" "last run failed: journalctl ${sc[*]} -u $svc -n 30"
      else
        local next; next=$(systemctl "${sc[@]}" show -p NextElapseUSecRealtime --value "$u")
        r ok "watch:$u" "${next:+next: $next}"
      fi
    else
      systemctl "${sc[@]}" is-active -q "$u" && r ok "watch:$u" "" \
        || r fail "watch:$u" "$(systemctl "${sc[@]}" is-active "$u" 2>/dev/null)"
    fi
  }
  for u in $WATCH_USER_UNITS; do watch user "$u"; done
  for u in $WATCH_SYSTEM_UNITS; do watch system "$u"; done
fi
if ! skip containers && has podman; then
  for c in $WATCH_CONTAINERS; do
    s=$(podman inspect -f '{{.State.Status}}' "$c" 2>/dev/null || echo missing)
    [ "$s" = running ] && r ok "container:$c" "" || r fail "container:$c" "$s: podman start $c"
  done
fi

# --- network: DNS, HTTPS, tailnet
if ! skip network; then
  getent hosts github.com >/dev/null && r ok dns "" || r fail dns "can't resolve github.com"
  curl -fsS -m 8 -o /dev/null https://github.com 2>/dev/null && r ok internet "" || r fail internet "HTTPS to github.com failed"
fi
if ! skip tailscale && has tailscale; then
  ts=$(tailscale status --json 2>/dev/null)
  state=$(jq -r '.BackendState // "unknown"' <<<"$ts")
  [ "$state" = Running ] && r ok tailscale "" || r fail tailscale "backend $state: tailscale up"
  while IFS= read -r peer; do
    [ -z "$peer" ] && continue
    online=$(jq -r --arg p "$peer" '[.Peer[]? | select(.HostName == $p) | .Online] | first // "missing"' <<<"$ts")
    [ "$online" = true ] && r ok "peer:$peer" "" || r warn "peer:$peer" "offline"
  done < <(tr ',' '\n' <<<"$WATCH_PEERS" | sed 's/^ *//; s/ *$//')
fi

# --- report
ok=0 warn=0 fail=0 lines=()
for line in "${out[@]}"; do
  IFS=$'\t' read -r l c d <<<"$line"
  case "$l" in ok) ok=$((ok+1)) ;; warn) warn=$((warn+1)) ;; fail) fail=$((fail+1)) ;; esac
  if [ "$l" != ok ] || [ $verbose = 1 ]; then lines+=("$(printf '%-4s %-30s %s' "$l" "$c" "$d")"); fi
done
if [ $((warn+fail)) = 0 ]; then summary="homelab: all green ($ok checks)"; else summary="homelab: $ok ok, $warn warn, $fail fail"; fi

mkdir -p "$STATE"
{ printf '%s\n' "${lines[@]}"; echo "$summary"; } | sed '/^$/d' > "$STATE/last.txt"
date -Is >> "$STATE/last.txt"
if [ $json = 1 ]; then
  printf '%s\n' "${out[@]}" | jq -R 'split("\t") | {level: .[0], check: .[1], detail: .[2]}' | jq -s .
else
  [ ${#lines[@]} -gt 0 ] && printf '%s\n' "${lines[@]}"
  echo "$summary"
fi
if [ $notify = 1 ] && [ $((warn+fail)) -gt 0 ] && has notify-send; then
  urgency=normal; [ $fail -gt 0 ] && urgency=critical
  notify-send -u "$urgency" -a homelab "$summary" "$(printf '%s\n' "${lines[@]}" | head -6 | cut -c1-90)"
fi
[ $fail = 0 ]
