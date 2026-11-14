# Double-click entry point (start.cmd runs this).
#
# tools\start_services.ps1 is the one launcher: it starts the downloader on 8080,
# the song service on 8090 and the site on 5001, starts cloudflared, publishes the
# tunnel's new address to the site so a phone can find it, and registers
# songsvc://. The logon entry and the watchdog run that same file.
#
# This file used to be a second, older copy of all that. It started a tunnel but
# never told the site about it, so a phone kept the last address it had been given
# and reported the AI as off while the PC was fine - the stale-address trap in the
# README. One launcher means one behaviour; nothing is duplicated here on purpose.

[CmdletBinding()]
param(
    [switch]$NoTunnel,
    [switch]$NoWarm,
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'

$launcher = Join-Path $PSScriptRoot 'tools\start_services.ps1'
if (-not (Test-Path $launcher)) {
    Write-Host "Missing $launcher"
    exit 1
}

$arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $launcher)
if ($NoTunnel) { $arguments += '-NoTunnel' }
if ($NoWarm) { $arguments += '-NoWarm' }
if ($Quiet) { $arguments += '-Quiet' }

& powershell @arguments
$code = $LASTEXITCODE

# The launcher is safe to repeat, so opening the site is the only extra thing a
# double-click does: it is what someone clicking this actually wants next.
if (-not $Quiet) {
    Write-Host ''
    Write-Host 'Opening http://127.0.0.1:5001/'
    Start-Process 'http://127.0.0.1:5001/'
}

exit $code
