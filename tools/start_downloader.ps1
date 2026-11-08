<#
    Start the download service on its own.

    The page downloads by asking a process on this computer. That process does
    not have to be the AI app: downloader_service is Flask and yt-dlp - about
    60 MB of RAM, no GPU, no models - and it is enough. Start this when you want
    downloads, close the window to stop it.

    Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File tools\start_downloader.ps1
            powershell -NoProfile -ExecutionPolicy Bypass -File tools\start_downloader.ps1 -Hidden
#>

[CmdletBinding()]
param(
    [int]$Port = 8080,
    [switch]$Hidden
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$service = Join-Path $root 'downloader_service'
$python = Join-Path $service '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    Write-Host 'First run: creating the downloader environment (a minute or two).'
    python -m venv (Join-Path $service '.venv')
    & $python -m pip install -q --disable-pip-version-check -r (Join-Path $service 'requirements.txt')
}

$running = netstat -ano | Select-String ":$Port\s" | Select-String 'LISTENING'
if ($running) {
    Write-Host "The download service is already running on 127.0.0.1:$Port."
} else {
    Write-Host "Starting the download service on 127.0.0.1:$Port..."
    $env:PORT = "$Port"
    $args = @('app.py')
    if ($Hidden) {
        Start-Process -FilePath $python -ArgumentList $args -WorkingDirectory $service `
            -WindowStyle Hidden -RedirectStandardOutput (Join-Path $root 'build\downloader_out.log') `
            -RedirectStandardError (Join-Path $root 'build\downloader_err.log') | Out-Null
    } else {
        Start-Process -FilePath $python -ArgumentList $args -WorkingDirectory $service | Out-Null
    }
}

for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 700
    $code = & curl.exe -s -o NUL -w '%{http_code}' --max-time 3 "http://127.0.0.1:$Port/health"
    if ($code -eq '200') { break }
}

$health = & curl.exe -s --max-time 5 "http://127.0.0.1:$Port/health"
if ($health) {
    Write-Host "Ready: $health"
    Write-Host 'Leave it running while you download. Close its window to stop it.'
} else {
    Write-Host 'It did not answer. See build\downloader_err.log.'
}
