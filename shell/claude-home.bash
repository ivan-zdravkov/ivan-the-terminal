# shellcheck shell=bash
# Every interactive `claude` starts in ivan-the-terminal, so its CLAUDE.md, skills, hooks and memory always load.
# The launch directory is added with --add-dir; for your own repos (under $ITT_REPOS) its CLAUDE.md loads too.
# Runs in place instead when launched:
#   - inside ivan-the-terminal or any checkout, worktree or clone of it (keeps that checkout's own hooks)
#   - inside a git repo outside $ITT_REPOS (an untrusted clone must not meet your personal context)
# Bypass: CLAUDE_HERE=1 claude ...   (e.g. to --resume a session that belongs to another directory)
# Headless runs (-p/--print) and scripts are untouched: shell functions don't exist there.
claude() {
  local home="${ITT_HOME:-$HOME/Repositories/ivan-the-terminal}" repos="${ITT_REPOS:-$HOME/Repositories}"
  local here arg top common
  for arg in "$@"; do
    case "$arg" in -p|--print) command claude "$@"; return ;; esac
  done
  if [ -n "${CLAUDE_HERE:-}" ] || [ ! -d "$home" ]; then command claude "$@"; return; fi
  here=$(pwd -P) home=$(cd "$home" && pwd -P) repos=$(cd "$repos" 2>/dev/null && pwd -P || echo "$repos")
  if top=$(git -C "$here" rev-parse --show-toplevel 2>/dev/null); then
    common=$(git -C "$here" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
    if [ "$common" = "$(git -C "$home" rev-parse --path-format=absolute --git-common-dir)" ] \
      || { [ -f "$top/tools/leakguard/leakguard.py" ] && grep -qs leakguard.py "$top/.claude/settings.json"; }; then
      command claude "$@"; return  # a checkout, worktree or clone of ivan-the-terminal: keep its own hooks
    fi
    case "$top/" in
      "$repos/"*) ;;
      *) command claude "$@"; return ;;  # someone else's repo: no personal context
    esac
    (cd "$home" && CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1 command claude --add-dir "$here" "$@")
    return
  fi
  (cd "$home" && command claude --add-dir "$here" "$@")
}
