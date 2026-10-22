# shellcheck shell=bash
# Every interactive `claude` starts in ivan-the-terminal, so its CLAUDE.md, skills, hooks and memory
# always load. The directory you launched from is added with --add-dir, and its CLAUDE.md is loaded too.
# Bypass: CLAUDE_HERE=1 claude ...   (e.g. to --resume a session that belongs to another directory)
# Headless runs (-p/--print) and scripts are untouched: shell functions don't exist there.
claude() {
  local home="${ITT_HOME:-$HOME/Repositories/ivan-the-terminal}" here arg
  for arg in "$@"; do
    case "$arg" in -p|--print) command claude "$@"; return ;; esac
  done
  if [ -n "${CLAUDE_HERE:-}" ] || [ ! -d "$home" ]; then command claude "$@"; return; fi
  here=$(pwd -P)
  home=$(cd "$home" && pwd -P)
  case "$here/" in
    "$home/"*) command claude "$@" ;;
    *) (cd "$home" && CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1 command claude --add-dir "$here" "$@") ;;
  esac
}
