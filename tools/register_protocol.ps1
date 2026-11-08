<#
    Let the website ask this PC to start its AI services.

    A browser tab cannot start a program - that is the sandbox, not a missing
    feature - but Windows can be told that a link click should run one. This
    registers a songsvc:// scheme for the current user only (HKCU, no
    administrator, nothing system-wide), pointing at start_services.ps1:

        songsvc://start

    The page then offers a button that navigates there. The browser asks once
    whether to open it, the services start, and the page picks them up.

    Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File tools\register_protocol.ps1
    Undo:   Remove-Item -Recurse 'HKCU:\Software\Classes\songsvc'
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $root 'tools\start_services.ps1'
if (-not (Test-Path $launcher)) { throw "Missing $launcher" }

$command = 'powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $launcher + '"'
$base = 'HKCU:\Software\Classes\songsvc'

New-Item -Path $base -Force | Out-Null
Set-ItemProperty -Path $base -Name '(default)' -Value 'URL:Song services launcher'
New-ItemProperty -Path $base -Name 'URL Protocol' -Value '' -PropertyType String -Force | Out-Null

New-Item -Path "$base\DefaultIcon" -Force | Out-Null
Set-ItemProperty -Path "$base\DefaultIcon" -Name '(default)' -Value 'powershell.exe,0'

New-Item -Path "$base\shell\open\command" -Force | Out-Null
Set-ItemProperty -Path "$base\shell\open\command" -Name '(default)' -Value $command

Write-Host "registered: songsvc://start"
Write-Host "runs: $command"
