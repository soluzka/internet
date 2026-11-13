<#
    Make the services come back by themselves.

    Two entries, plus one process that stays around:

      HKCU Run key 'AI song services'   launcher -Watch at every logon
      Startup folder 'AI song services.cmd'   the same thing, as a second chance
      the -Watch process                checks both ports every 2 minutes and
                                        starts a service that has gone away

    No administrator is needed, so this cannot use Task Scheduler: registering a
    task, even one for the current user, returns Access denied here.

    Why both entries: on 8 Nov 2026 the PC booted at 18:41:26 and Explorer logged
    in at 18:41:38, yet the Startup entry produced no launcher run at all - the
    services stayed down until one was started by hand. The Run key is what the
    programs on this machine that do start reliably (Steam, Discord) use. The
    duplicate is harmless: the watchdog checks for an existing one and exits.

    Remove with:  Remove-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' 'AI song services'
                  Remove-Item (Join-Path ([Environment]::GetFolderPath('Startup')) 'AI song services.cmd')
                  Stop-Process -Id (Get-CimInstance Win32_Process -Filter "Name like '%powershell%'" |
                      Where-Object { $_.CommandLine -like '*-Watch*' -and $_.CommandLine -like '*start_services*' }).ProcessId

    Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_autostart.ps1
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $PSScriptRoot 'start_services.ps1'
$command = 'powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $launcher + '" -Watch'
# The Startup entry is a .cmd, and cmd keeps its window open until the command
# it ran exits - the watchdog never exits. `start "" /min` hands it off, so no
# black console box is left on the desktop after logon.
$startupCommand = 'start "" /min ' + $command

# --- logon: registry Run key ----------------------------------------------
$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
Set-ItemProperty -Path $runKey -Name 'AI song services' -Value $command
Write-Host "run key set: $runKey\AI song services"

# --- logon: Startup folder, as a second chance ----------------------------
$startup = [Environment]::GetFolderPath('Startup')
$cmd = Join-Path $startup 'AI song services.cmd'
Set-Content -Path $cmd -Encoding ascii -Value @(
    '@echo off',
    'rem Added by tools\install_autostart.ps1: starts the local AI services at logon.',
    $startupCommand
)
Write-Host "startup entry: $cmd"

# --- one watchdog now, which also starts anything missing -----------------
$existing = @(Get-CimInstance Win32_Process -Filter "Name like '%powershell%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*start_services.ps1*' -and $_.CommandLine -like '*-Watch*' })

if ($existing.Count -gt 0) {
    Write-Host "watchdog already running (pid $($existing[0].ProcessId)); it will start anything missing"
} else {
    Write-Host 'starting the services and the watchdog in the background...'
    Start-Process -FilePath 'powershell' -WindowStyle Hidden -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $launcher, '-Watch'
    ) | Out-Null
    Write-Host 'done: they start at logon and come back on their own if they die.'
}
