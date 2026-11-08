<#
    Make the services come back by themselves.

    Writes a launcher into this user's Startup folder (no administrator needed,
    nothing installed system-wide) and starts everything once immediately, so the
    website works now and again after every logon.

    Remove it again with:  Remove-Item (Join-Path ([Environment]::GetFolderPath('Startup')) 'AI song services.cmd')

    Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_autostart.ps1
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$startup = [Environment]::GetFolderPath('Startup')
$launcher = Join-Path $startup 'AI song services.cmd'

$lines = @(
    '@echo off',
    'rem Added by tools\install_autostart.ps1: starts the local AI services at logon.',
    "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$root\tools\start_services.ps1`""
)
Set-Content -Path $launcher -Value $lines -Encoding ascii
Write-Host "installed: $launcher"

# Started detached, exactly the way the Startup entry will do it, so this
# returns at once instead of sitting through a torch import and a warm load.
Write-Host 'starting the services now in the background...'
Start-Process -FilePath 'powershell' -WindowStyle Hidden -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass',
    '-File', (Join-Path $PSScriptRoot 'start_services.ps1')
) | Out-Null
Write-Host 'done: they start themselves at every logon from now on.'
