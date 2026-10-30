#!/usr/bin/env bash
# system-updates: show (default) or apply pending updates on an atomic Fedora / Bazzite machine.
#   run             list what's pending per layer
#   run --apply     apply user-level layers (flatpak, brew, distrobox with --containers)
# OS image and firmware need auth or a reboot, so they're printed as commands for the user.
set -uo pipefail
apply=0 containers=0
for a in "$@"; do case "$a" in --apply) apply=1 ;; --containers) containers=1 ;; esac; done
has() { command -v "$1" >/dev/null; }
step() { printf '==> %s\n' "$*"; }

if has rpm-ostree; then
  st=$(rpm-ostree status --json 2>/dev/null)
  staged=$(jq -r '.deployments[] | select(.staged) | .version' <<<"$st")
  booted=$(jq -r '.deployments[] | select(.booted) | .version' <<<"$st")
  if [ -n "$staged" ]; then step "os: $staged staged (booted $booted). Reboot to apply: systemctl reboot"
  else step "os: $booted booted, nothing staged. Full update: ujust update (asks for your password)"; fi
fi

if has flatpak; then
  n=$(flatpak remote-ls --updates --columns=application 2>/dev/null | grep -c .)
  step "flatpak: $n pending"
  if [ $apply = 1 ] && [ "$n" -gt 0 ]; then flatpak update -y --noninteractive 2>&1 | tail -3; flatpak uninstall --unused -y --noninteractive >/dev/null 2>&1; fi
fi

if has brew; then
  n=$(HOMEBREW_NO_AUTO_UPDATE=1 brew outdated --quiet 2>/dev/null | grep -c .)
  step "brew: $n outdated"
  if [ $apply = 1 ]; then brew update -q >/dev/null 2>&1; brew upgrade -q 2>&1 | tail -3; brew cleanup -q >/dev/null 2>&1; fi
fi

if has distrobox; then
  boxes=$(distrobox list --no-color 2>/dev/null | tail -n +2 | cut -d'|' -f2 | xargs)
  step "distrobox: ${boxes:-none}"
  if [ $apply = 1 ] && [ $containers = 1 ] && [ -n "$boxes" ]; then distrobox upgrade --all 2>&1 | tail -3; fi
fi

if has fwupdmgr; then
  fw=$(timeout 30 fwupdmgr get-updates --json 2>/dev/null | jq -r '[.Devices[]? | "\(.Name) \(.Releases[0].Version // "")"] | join("; ")')
  step "firmware: ${fw:-current}"
  [ -n "$fw" ] && echo "    apply: fwupdmgr update (may reboot)"
fi

if has claude; then step "claude: $(claude --version 2>/dev/null) (self-updates)"; fi
[ $apply = 1 ] && step "done. Re-check: itt run homelab-check"
