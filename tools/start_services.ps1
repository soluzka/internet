<#
    Start everything the website needs on this computer, and do nothing if it is
    already running.

    Two processes, and the page finds both on its own:

      8080  downloader_service   Flask + yt-dlp, no GPU, about 60 MB
      8090  song_service         ACE-Step on CUDA, warmed up so the first
                                 composed song does not also pay for the load

    Safe to run repeatedly: each service is probed first and only started when it
    is not answering. Run it from the Startup folder and the whole thing comes
    back after a reboot with no one clicking anything.

    Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File tools\start_services.ps1
#>

[CmdletBinding()]
param(
    [int]$DownloadPort = 8080,
    [int]$SongPort = 8090,
    [switch]$NoWarm,
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

# A line per run, so "the site started it" can be checked instead of assumed.
try {
    Add-Content -Path (Join-Path $root 'build\launcher_trace.txt') `
        -Value ('{0:yyyy-MM-dd HH:mm:ss} launcher ran' -f (Get-Date))
} catch { }

function Say([string]$text) {
    if (-not $Quiet) { Write-Host $text }
}

# Keep songsvc:// pointing at this copy of the launcher, every run. A moved
# folder, a restored machine or a first start all end the same way: the site's
# Start the AI button works without anyone running another script. Registering
# twice is harmless, so it simply checks and repairs.
function Ensure-Protocol {
    $launcher = Join-Path $root 'tools\start_services.ps1'
    if (-not (Test-Path $launcher)) { return }
    $wanted = 'powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $launcher + '"'
    $base = 'HKCU:\Software\Classes\songsvc'
    try {
        $current = (Get-ItemProperty -Path "$base\shell\open\command" -ErrorAction SilentlyContinue).'(default)'
        if ($current -eq $wanted) { return }
        New-Item -Path $base -Force | Out-Null
        Set-ItemProperty -Path $base -Name '(default)' -Value 'URL:Song services launcher'
        New-ItemProperty -Path $base -Name 'URL Protocol' -Value '' -PropertyType String -Force | Out-Null
        New-Item -Path "$base\shell\open\command" -Force | Out-Null
        Set-ItemProperty -Path "$base\shell\open\command" -Name '(default)' -Value $wanted
        Say 'registered songsvc:// for the Start the AI button'
    } catch {
        Say "could not register songsvc://: $($_.Exception.Message)"
    }
}

Ensure-Protocol

function Answers([int]$port) {
    $code = & curl.exe -s -o NUL -w '%{http_code}' --max-time 3 "http://127.0.0.1:$port/health"
    return ($code -eq '200')
}

# Health only answers once Flask is listening, which for the song service is
# after torch imports - about 40 s. Probing alone therefore says "not running"
# during exactly the window a second click lands in, and the second click used
# to start a second copy that then failed to bind 8090. Asking whether the
# process exists covers that window: one launcher run, one service.
function Starting([string]$marker) {
    $found = Get-CimInstance Win32_Process -Filter "Name like '%python%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*$marker*" }
    return [bool]$found
}

# Nothing here waits for a model. Importing torch and warming 3.5B parameters
# takes a minute or two, and a launcher that sits through it looks hung: the
# process is started and this returns, health is checked separately.

# --- downloader ----------------------------------------------------------
if (Answers $DownloadPort) {
    Say "downloader already on 127.0.0.1:$DownloadPort"
} elseif (Starting '*downloader_service*') {
    Say 'downloader is still starting, leaving it alone'
} else {
    $service = Join-Path $root 'downloader_service'
    $python = Join-Path $service '.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) {
        Say 'downloader: creating its environment (a minute or two)'
        python -m venv (Join-Path $service '.venv')
        & $python -m pip install -q --disable-pip-version-check -r (Join-Path $service 'requirements.txt')
    }
    $env:PORT = "$DownloadPort"
    Start-Process -FilePath $python -ArgumentList 'app.py' -WorkingDirectory $service `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $root 'build\downloader_out.log') `
        -RedirectStandardError (Join-Path $root 'build\downloader_err.log') | Out-Null
    Say "downloader starting on 127.0.0.1:$DownloadPort (log: build\downloader_err.log)"
}

# --- song service, on CUDA ----------------------------------------------
if (Answers $SongPort) {
    Say "song service already on 127.0.0.1:$SongPort"
} elseif (Starting '*song_service*') {
    Say 'song service is still starting (torch import takes about 40 s), leaving it alone'
} else {
    $service = Join-Path $root 'song_service'
    $python = Join-Path $service '.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) {
        Say 'song service: run song_service\install.py first (it installs the CUDA torch)'
        exit 1
    }

    # SONG_WARM puts the 3.5B model on the card now, in the background, instead
    # of on the first compose. LYRICS_DEVICE is left unset so app.py picks cuda
    # when torch can see a card and cpu when it cannot.
    $env:SONG_PORT = "$SongPort"
    $env:SONG_WARM = if ($NoWarm) { '0' } else { '1' }
    Start-Process -FilePath $python -ArgumentList 'app.py' -WorkingDirectory $service `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $service 'logs\service_out.log') `
        -RedirectStandardError (Join-Path $service 'logs\service_err.log') | Out-Null
    Say "song service starting on 127.0.0.1:$SongPort, warming CUDA (log: song_service\logs\service_out.log)"
}

$songHealth = & curl.exe -s --max-time 4 "http://127.0.0.1:$SongPort/health"
if ($songHealth) { Say "song now: $songHealth" } else { Say 'song: still loading, check again in a minute' }
