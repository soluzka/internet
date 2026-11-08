# Diagnose the local tunnel: which cloudflared processes exist, what they point
# at, and which public URL the log recorded.
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" |
    ForEach-Object { "{0} :: {1}" -f $_.ProcessId, $_.CommandLine }

if (Test-Path 'tunnel.log') {
    Select-String -Path 'tunnel.log' -Pattern 'trycloudflare.com' |
        ForEach-Object { "LOG: " + $_.Line }
} else {
    'no tunnel.log'
}

try {
    $local = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8090/health' -TimeoutSec 5
    "local 8090: $($local.StatusCode) $($local.Content)"
} catch {
    "local 8090: down"
}
