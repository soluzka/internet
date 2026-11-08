# Starts everything the song feature needs, in order, and prints the public
# address of the model so the deployed page can reach the GPU on this machine:
#
#   1. song_service  - the lyric model and ACE-Step on the GPU (port 8090)
#   2. app.py        - the site (port 5001)
#   3. cloudflared   - a Quick Tunnel giving the model an https address
#
# Everything already running is left alone, so double-clicking twice is safe.

$ErrorActionPreference = 'Continue'
$root = $PSScriptRoot
Set-Location $root

function Test-Endpoint($url) {
    try {
        return (Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 5).StatusCode -eq 200
    } catch {
        return $false
    }
}

$songDir = Join-Path $root 'song_service'
$songExe = Join-Path $songDir '.venv\Scripts\python.exe'
$webExe = Join-Path $root '.venv\Scripts\python.exe'
$logs = Join-Path $songDir 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null

# --- 1. Song model service ------------------------------------------------
if (Test-Endpoint 'http://127.0.0.1:8090/health') {
    Write-Host 'Song model: already running on 8090.'
} elseif (-not (Test-Path $songExe)) {
    Write-Host "Song model: $songExe is missing. Run song_service/install.py first."
} else {
    Write-Host 'Song model: starting (the GPU loads the weights on first use)...'
    $env:SONG_PORT = '8090'
    Start-Process -FilePath $songExe -ArgumentList 'app.py' -WorkingDirectory $songDir `
        -RedirectStandardOutput (Join-Path $logs 'service.log') `
        -RedirectStandardError (Join-Path $logs 'service.err') -WindowStyle Hidden
    for ($i = 0; $i -lt 90; $i++) {
        Start-Sleep -Seconds 2
        if (Test-Endpoint 'http://127.0.0.1:8090/health') { break }
    }
    if (Test-Endpoint 'http://127.0.0.1:8090/health') {
        Write-Host 'Song model: ready.'
    } else {
        Write-Host 'Song model: did not answer. See song_service\logs\service.err.'
    }
}

# --- 2. The site ----------------------------------------------------------
if (Test-Endpoint 'http://127.0.0.1:5001/') {
    Write-Host 'Site: already running on 5001.'
} else {
    Write-Host 'Site: starting...'
    Start-Process -FilePath $webExe -ArgumentList 'app.py' -WorkingDirectory $root `
        -RedirectStandardOutput (Join-Path $root 'run_web.log') `
        -RedirectStandardError (Join-Path $root 'run_web.err') -WindowStyle Hidden
    for ($i = 0; $i -lt 45; $i++) {
        Start-Sleep -Seconds 2
        if (Test-Endpoint 'http://127.0.0.1:5001/') { break }
    }
    Write-Host 'Site: ready.'
}

# --- 3. The tunnel --------------------------------------------------------
# Quick Tunnels ignore --url when cloudflared reads ~/.cloudflared/config.yml:
# that file's ingress rules win and the catch-all answers 404. Passing an empty
# --config keeps the tunnel bound to the port below.
$cloudflared = Join-Path $root 'tools\bin\cloudflared.exe'
$tunnelLog = Join-Path $root 'tunnel.log'
$url = ''

if (-not (Test-Path $cloudflared)) {
    Write-Host 'Tunnel: cloudflared is missing, so only this machine can use the model.'
} else {
    Get-Process cloudflared -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $cloudflared } |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    Remove-Item $tunnelLog -ErrorAction SilentlyContinue

    Start-Process -FilePath $cloudflared -WorkingDirectory $root -ArgumentList @(
        'tunnel', '--config', 'tools\bin\quick-tunnel.yml',
        '--url', 'http://127.0.0.1:8090', '--no-autoupdate',
        '--logfile', 'tunnel.log', '--loglevel', 'info'
    ) -WindowStyle Hidden

    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 2
        if (-not (Test-Path $tunnelLog)) { continue }
        $found = Select-String -Path $tunnelLog -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' |
            ForEach-Object { $_.Matches[0].Value } | Select-Object -First 1
        if ($found) { $url = $found; break }
    }

    if ($url) {
        try { Set-Clipboard -Value $url } catch {}
        Write-Host ''
        Write-Host 'The model is reachable at:'
        Write-Host "  $url"
        Write-Host ''
        Write-Host 'That address is already copied to the clipboard. On the live site,'
        Write-Host 'press "Song designer", then "Connect my model" and paste it in.'
        Write-Host 'A new tunnel gets a new address, so paste again after a restart.'
    } else {
        Write-Host 'Tunnel: no address was reported. See tunnel.log.'
    }
}

Write-Host ''
Write-Host 'Opening http://127.0.0.1:5001/'
Start-Process 'http://127.0.0.1:5001/'
