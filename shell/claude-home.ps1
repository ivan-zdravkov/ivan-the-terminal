# Every interactive `claude` starts in ivan-the-terminal, so its CLAUDE.md, skills, hooks and memory always load.
# PowerShell twin of claude-home.bash; bootstrap.py dot-sources it from the PowerShell 7 and 5.1 profiles.
# The launch directory is added with --add-dir; for your own repos (under $env:ITT_REPOS) its CLAUDE.md loads too.
# Runs in place instead when launched:
#   - inside ivan-the-terminal or any checkout, worktree or clone of it (keeps that checkout's own hooks)
#   - inside a git repo outside $env:ITT_REPOS (an untrusted clone must not meet your personal context)
# Bypass: $env:CLAUDE_HERE=1; claude ...   (e.g. to --resume a session that belongs to another directory)
# Headless runs (-p/--print) and scripts are untouched: profiles don't load there.
$global:IttClaudeHome = Split-Path -Parent $PSScriptRoot

function global:claude {
  $exe = Get-Command claude -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $exe) { Write-Error 'claude: Claude Code is not installed'; return }
  $home_ = if ($env:ITT_HOME) { $env:ITT_HOME } else { $global:IttClaudeHome }
  if ($env:CLAUDE_HERE -or -not (Test-Path $home_) -or ($args -contains '-p') -or ($args -contains '--print')) {
    & $exe @args; return
  }
  $full = { param($p) [IO.Path]::GetFullPath($p).TrimEnd('\', '/') }
  $here = (Get-Location).ProviderPath
  $home_ = & $full $home_
  $repos = & $full $(if ($env:ITT_REPOS) { $env:ITT_REPOS } else { Split-Path -Parent $home_ })
  $top = git -C $here rev-parse --show-toplevel 2>$null
  if ($LASTEXITCODE -eq 0 -and $top) {
    $top = & $full $top
    $common = git -C $here rev-parse --path-format=absolute --git-common-dir 2>$null
    $homeCommon = git -C $home_ rev-parse --path-format=absolute --git-common-dir 2>$null
    $settings = Join-Path $top '.claude\settings.json'
    $clone = (Test-Path (Join-Path $top 'tools\leakguard\leakguard.py')) -and
             (Test-Path $settings) -and (Select-String -Path $settings -SimpleMatch 'leakguard.py' -Quiet)
    if (($common -and $common -eq $homeCommon) -or $clone) { & $exe @args; return }  # a checkout of ivan-the-terminal
    if (-not "$top\".StartsWith("$repos\", [StringComparison]::OrdinalIgnoreCase)) { & $exe @args; return }  # someone else's repo
    $env:CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD = '1'
  }
  Push-Location $home_
  try { & $exe --add-dir $here @args }
  finally { Pop-Location; Remove-Item Env:CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD -ErrorAction SilentlyContinue }
}
