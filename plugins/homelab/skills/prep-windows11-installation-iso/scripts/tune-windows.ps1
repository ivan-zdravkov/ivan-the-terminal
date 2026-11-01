# Desktop and gaming tune-up for Windows 11. Run elevated, as the user it is for. Safe to re-run.
# Runs at first logon from install-apps.ps1, or on a live machine via `itt run prep-windows11-installation-iso tune`.
# Windows PowerShell 5.1 compatible: it runs before PowerShell 7 is installed.
#   -Taskbar       words: center | left, autohide, alltray (every tray icon visible)
#   -Pins          comma-separated Start menu shortcut names, left to right ("File Explorer" is built in)
#   -AutostartOff  wildcard patterns of Run entries to disable (Task Manager's "Disabled", survives app updates)
#   -Debloat       words: Edge FaxScan CrossDevice
#   -StoreApps     Microsoft Store ids installed with winget
#   -Logon         only the per-logon part (tray icons, autostart); what the scheduled task runs
param(
    [string]$Taskbar = 'center autohide alltray',
    [string]$Pins = '',
    [string]$AutostartOff = '',
    [string]$Debloat = '',
    [string]$StoreApps = '',
    [switch]$Logon,
    [string]$Log = ''
)
$ErrorActionPreference = 'Stop'
if ($Log) { Start-Transcript -Path $Log -Append | Out-Null }
$report = New-Object System.Collections.Generic.List[string]
$home_ = Join-Path $env:ProgramFiles 'ivan-the-terminal'  # admin-only: the elevated logon task runs from here
$task = 'ivan-the-terminal desktop'
$words = $Taskbar.ToLower().Split(' ', [StringSplitOptions]::RemoveEmptyEntries)
$explorerChanged = $false

function Step($name, [scriptblock]$body) {
    try { $r = & $body; if ($r) { $report.Add("${name}: $r") } }
    catch { $report.Add("${name}: FAILED $($_.Exception.Message)") }
}

function SetValue($path, $name, $value, $type = 'DWord') {
    if (-not (Test-Path $path)) { New-Item -Path $path -Force | Out-Null }
    $old = (Get-ItemProperty -Path $path -Name $name -ErrorAction SilentlyContinue).$name
    if ("$old" -ne "$value") { New-ItemProperty -Path $path -Name $name -Value $value -PropertyType $type -Force | Out-Null; return $true }
    return $false
}

function PromoteTrayIcons {
    $n = 0
    foreach ($k in Get-ChildItem 'HKCU:\Control Panel\NotifyIconSettings' -ErrorAction SilentlyContinue) {
        if ((Get-ItemProperty $k.PSPath).IsPromoted -ne 1) { Set-ItemProperty $k.PSPath -Name IsPromoted -Value 1 -Type DWord; $n++ }
    }
    if ($n) { "$n icon(s) shown" }
}

function DisableAutostart {
    if (-not $AutostartOff.Trim()) { return }
    $patterns = $AutostartOff.Split(' ', [StringSplitOptions]::RemoveEmptyEntries)
    $off = [byte[]](3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)  # what Task Manager writes for "Disabled"
    $approved = 'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved'
    $sources = @(
        @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Run', "HKCU:\$approved\Run"),
        @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run', "HKLM:\$approved\Run"),
        @('HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run', "HKLM:\$approved\Run32"))
    $done = @()
    foreach ($s in $sources) {
        $run = Get-ItemProperty $s[0] -ErrorAction SilentlyContinue
        if (-not $run) { continue }
        foreach ($p in $run.PSObject.Properties | Where-Object { $_.Name -notlike 'PS*' }) {
            if (-not ($patterns | Where-Object { $p.Name -like $_ })) { continue }
            $cur = (Get-ItemProperty $s[1] -Name $p.Name -ErrorAction SilentlyContinue).($p.Name)
            if ($cur -and $cur[0] -eq 3) { continue }
            if (-not (Test-Path $s[1])) { New-Item -Path $s[1] -Force | Out-Null }
            New-ItemProperty -Path $s[1] -Name $p.Name -Value $off -PropertyType Binary -Force | Out-Null
            $done += $p.Name
        }
    }
    if ($done) { "disabled $($done -join ', ')" }
}

if ($Logon) {
    if ($words -contains 'alltray') { Step 'tray' { PromoteTrayIcons } }
    Step 'autostart' { DisableAutostart }
    $report | ForEach-Object { Write-Output $_ }
    if ($Log) { Stop-Transcript | Out-Null }
    exit 0
}

# ---- debloat ----------------------------------------------------------------------------------
$remove = $Debloat.Split(' ', [StringSplitOptions]::RemoveEmptyEntries)
if ($remove -contains 'Edge') {
    Step 'Edge' {
        # Only the browser: the WebView2 runtime that apps embed stays. Uninstallable in EEA regions.
        $policy = 'HKLM:\SOFTWARE\Policies\Microsoft\EdgeUpdate'
        SetValue $policy 'Install{56EB18F8-B008-4CBD-B6D2-8C97FE7E9062}' 0 | Out-Null  # never reinstall Edge Stable
        SetValue 'HKLM:\SOFTWARE\Microsoft\EdgeUpdate' 'DoNotUpdateToEdgeWithChromium' 1 | Out-Null
        $exe = Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'
        if (-not (Test-Path $exe)) { return 'not installed' }
        $setup = Get-ChildItem (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\*\Installer\setup.exe') |
            Sort-Object LastWriteTime | Select-Object -Last 1
        # the arguments of Settings > Apps > Uninstall, without asking
        Start-Process $setup.FullName -ArgumentList '--uninstall', '--msedge', '--channel=stable', '--system-level', '--force-uninstall' -Wait
        Get-AppxPackage -AllUsers Microsoft.MicrosoftEdge.Stable | Remove-AppxPackage -AllUsers -ErrorAction SilentlyContinue
        if (Test-Path $exe) { 'FAILED: still installed (outside the EEA Edge refuses to uninstall)' } else { 'removed' }
    }
}
if ($remove -contains 'FaxScan') {
    Step 'Fax and Scan' {
        $caps = Get-WindowsCapability -Online | Where-Object { $_.Name -like 'Print.Fax.Scan*' -and $_.State -eq 'Installed' }
        $caps | ForEach-Object { Remove-WindowsCapability -Online -Name $_.Name | Out-Null }
        $f = Get-WindowsOptionalFeature -Online -FeatureName FaxServicesClientPackage -ErrorAction SilentlyContinue
        if ($f -and $f.State -eq 'Enabled') { Disable-WindowsOptionalFeature -Online -FeatureName FaxServicesClientPackage -NoRestart | Out-Null }
        if ($caps -or ($f -and $f.State -eq 'Enabled')) { 'removed (printing untouched)' }
    }
}
if ($remove -contains 'CrossDevice') {
    Step 'Phone Link host' {
        $p = Get-AppxPackage -AllUsers MicrosoftWindows.CrossDevice
        $p | Remove-AppxPackage -AllUsers -ErrorAction SilentlyContinue
        Get-AppxProvisionedPackage -Online | Where-Object DisplayName -eq 'MicrosoftWindows.CrossDevice' |
            Remove-AppxProvisionedPackage -Online | Out-Null
        if ($p) { 'removed' }
    }
}

# ---- gaming -----------------------------------------------------------------------------------
Step 'gaming' {
    $c = @()
    if (SetValue 'HKLM:\SYSTEM\CurrentControlSet\Control\GraphicsDrivers' 'HwSchMode' 2) { $c += 'GPU scheduling on (reboot)' }
    if (SetValue 'HKCU:\Software\Microsoft\GameBar' 'AutoGameModeEnabled' 1) { $c += 'Game Mode on' }
    # background recording off: no capture overhead while playing
    $dvr = (SetValue 'HKCU:\System\GameConfigStore' 'GameDVR_Enabled' 0)
    $dvr = (SetValue 'HKCU:\Software\Microsoft\Windows\CurrentVersion\GameDVR' 'AppCaptureEnabled' 0) -or $dvr
    $dvr = (SetValue 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\GameDVR' 'AllowGameDVR' 0) -or $dvr
    if ($dvr) { $c += 'Game DVR off' }
    # "Optimizations for windowed games": flip-model presentation for DX10/11 games in windowed mode
    $gpu = 'HKCU:\Software\Microsoft\DirectX\UserGpuPreferences'
    $cur = "$((Get-ItemProperty $gpu -Name DirectXUserGlobalSettings -ErrorAction SilentlyContinue).DirectXUserGlobalSettings)"
    if ($cur -notmatch 'SwapEffectUpgradeEnable=1;') {
        $new = ($cur -replace 'SwapEffectUpgradeEnable=\d;', '') + 'SwapEffectUpgradeEnable=1;'
        SetValue $gpu 'DirectXUserGlobalSettings' $new 'String' | Out-Null
        $c += 'windowed-game optimizations on'
    }
    if ($c) { $c -join ', ' }
}

# ---- taskbar ----------------------------------------------------------------------------------
$adv = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced'
Step 'taskbar' {
    $c = @()
    if ($words -contains 'left' -or $words -contains 'center') {
        $align = if ($words -contains 'left') { 0 } else { 1 }
        if (SetValue $adv 'TaskbarAl' $align) { $c += $words | Where-Object { $_ -in 'left', 'center' } }
    }
    $stuck = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StuckRects3'
    $s = (Get-ItemProperty $stuck -ErrorAction SilentlyContinue).Settings
    if ($s) {
        $want = if ($words -contains 'autohide') { 3 } else { 2 }
        if ($s[8] -ne $want) { $s[8] = $want; Set-ItemProperty $stuck -Name Settings -Value $s; $c += "auto-hide $(if ($want -eq 3) { 'on' } else { 'off' })" }
    }
    if ($c) { $script:explorerChanged = $true; $c -join ', ' }
}
if ($words -contains 'alltray') { Step 'tray' { PromoteTrayIcons } }
Step 'autostart' { DisableAutostart }

if ($Pins.Trim()) {
    Step 'pins' {
        # Taskbar layout via the "Start Layout" policy: applied when the file changes (instantly on 26200+).
        # PinGeneration lets an unpinned app stay unpinned.
        $menus = @("$env:ProgramData\Microsoft\Windows\Start Menu\Programs", "$env:APPDATA\Microsoft\Windows\Start Menu\Programs")
        $xml = @(); $missing = @()
        foreach ($name in $Pins.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ }) {
            if ($name -eq 'File Explorer') { $xml += '<taskbar:DesktopApp DesktopApplicationID="Microsoft.Windows.Explorer" PinGeneration="1"/>'; continue }
            $lnk = Get-ChildItem $menus -Recurse -Filter "$name.lnk" -ErrorAction SilentlyContinue | Select-Object -First 1
            if (-not $lnk) { $missing += $name; continue }
            $path = $lnk.FullName.Replace($env:ProgramData, '%ALLUSERSPROFILE%').Replace($env:APPDATA, '%APPDATA%')
            $xml += "<taskbar:DesktopApp DesktopApplicationLinkPath=`"$([Security.SecurityElement]::Escape($path))`" PinGeneration=`"1`"/>"
        }
        $doc = @(
            '<?xml version="1.0" encoding="utf-8"?>',
            '<LayoutModificationTemplate xmlns="http://schemas.microsoft.com/Start/2014/LayoutModification"',
            '    xmlns:defaultlayout="http://schemas.microsoft.com/Start/2014/FullDefaultLayout"',
            '    xmlns:start="http://schemas.microsoft.com/Start/2014/StartLayout"',
            '    xmlns:taskbar="http://schemas.microsoft.com/Start/2014/TaskbarLayout" Version="1">',
            '  <CustomTaskbarLayoutCollection PinListPlacement="Replace">',
            '    <defaultlayout:TaskbarLayout>',
            '      <taskbar:TaskbarPinList>') + ($xml | ForEach-Object { "        $_" }) + @(
            '      </taskbar:TaskbarPinList>',
            '    </defaultlayout:TaskbarLayout>',
            '  </CustomTaskbarLayoutCollection>',
            '</LayoutModificationTemplate>')
        New-Item -ItemType Directory -Force $home_ | Out-Null
        $file = Join-Path $home_ 'taskbar-layout.xml'
        $text = ($doc -join "`r`n") + "`r`n"
        $changed = -not (Test-Path $file) -or ([IO.File]::ReadAllText($file) -ne $text)
        if ($changed) { [IO.File]::WriteAllText($file, $text, (New-Object Text.UTF8Encoding $false)) }
        $pol = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Explorer'
        $changed = (SetValue $pol 'StartLayoutFile' $file 'ExpandString') -or $changed
        $changed = (SetValue $pol 'LockedStartLayout' 1) -or $changed
        $r = if ($changed) { "$($xml.Count) pinned" } else { '' }
        if ($missing) { $r = "$r; not installed yet: $($missing -join ', ')".TrimStart('; ') }
        $r
    }
}

foreach ($id in $StoreApps.Split(' ', [StringSplitOptions]::RemoveEmptyEntries)) {
    Step "Store $id" {
        $winget = Get-Command winget -ErrorAction SilentlyContinue
        if (-not $winget) { return 'FAILED: winget not available yet; install it from the Store later' }
        & winget list --id $id --source msstore --accept-source-agreements *> $null
        if ($LASTEXITCODE -eq 0) { return }
        & winget install --id $id --source msstore --silent --accept-package-agreements --accept-source-agreements --disable-interactivity *> $null
        if ($LASTEXITCODE -eq 0) { 'installed' } else { "FAILED: winget exit $LASTEXITCODE" }
    }
}

# ---- every logon: new tray icons shown, launchers that re-added themselves disabled again ----------
if ($words -contains 'alltray' -or $AutostartOff.Trim()) {
    Step 'logon task' {
        New-Item -ItemType Directory -Force $home_ | Out-Null
        $dest = Join-Path $home_ 'tune-windows.ps1'
        if ($PSCommandPath -ne $dest) { Copy-Item $PSCommandPath $dest -Force }
        $arg = "-NoProfile -ExecutionPolicy Bypass -File `"$dest`" -Logon -Taskbar `"$Taskbar`""
        if ($AutostartOff.Trim()) { $arg += " -AutostartOff `"$AutostartOff`"" }
        # conhost --headless: no console window flashing every 15 minutes
        $action = New-ScheduledTaskAction -Execute 'conhost.exe' -Argument "--headless powershell.exe $arg"
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
        $trigger.Repetition = (New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 15)).Repetition
        $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
        Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
        'registered (at logon + every 15 min)'
    }
}

if ($explorerChanged) { Stop-Process -Name explorer -Force -ErrorAction SilentlyContinue }  # restarts on its own

# Last and time-boxed: it comes from Windows Update and waits behind any servicing already in progress.
Step '.NET Framework 3.5' {
    # older games and their launchers still need it
    if ((Get-WindowsOptionalFeature -Online -FeatureName NetFx3).State -eq 'Enabled') { return }
    $p = Start-Process dism.exe -ArgumentList '/Online', '/Enable-Feature', '/FeatureName:NetFx3', '/All', '/NoRestart', '/Quiet' -PassThru -WindowStyle Hidden
    if (-not $p.WaitForExit(900000)) { return 'still installing after 15 min (Windows Update busy); it finishes on its own' }
    if ($p.ExitCode -in 0, 3010) { 'enabled' } else { "FAILED: dism exit $($p.ExitCode)" }
}
$report | ForEach-Object { Write-Output $_ }
if ($Log) { Stop-Transcript | Out-Null }
exit 0
