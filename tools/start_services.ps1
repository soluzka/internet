<#
    Start everything the website needs on this computer, and do nothing if it is
    already running.

    Three processes, and the page finds them on its own:

      5001  app.py               the site itself: Flask, Socket.IO and the
                                 SQLite index
      8080  downloader_service   Flask + yt-dlp, no GPU, about 60 MB
      8090  song_service         ACE-Step on CUDA, warmed up so the first
                                 composed song does not also pay for the load

    Safe to run repeatedly: each service is probed first and only started when it
    is not answering. Run it at logon and the whole thing comes back after a
    reboot with no one clicking anything.

    A Quick Tunnel can be started too (-NoTunnel skips it), giving the model an
    https address from outside the home network; the address is published to the
    site so the page finds it without anyone pasting a new one.

    -Watch stays running afterwards and checks all three ports every two minutes,
    starting a service again if it has gone away. A logon entry only covers a
    reboot; this covers the machine staying on while a service dies, which is
    what happened on 8 Nov 2026 - the crash took both services and nothing was
    left to bring them back.

    Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File tools\start_services.ps1
            powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File tools\start_services.ps1 -Watch
#>

[CmdletBinding()]
param(
    [int]$WebPort = 5001,
    [int]$DownloadPort = 8080,
    [int]$SongPort = 8090,
    [switch]$NoWarm,
    [switch]$NoTunnel,
    [switch]$Quiet,
    [switch]$Watch
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

# A logon run has no console to read afterwards, so everything this run prints
# is also written to a file: "an error flashed up" is not diagnosable. A second
# run cannot take the same transcript, so failure here is not fatal.
try {
    Start-Transcript -Path (Join-Path $root 'build\launcher_run.log') -Append | Out-Null
} catch { }

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

function Trace([string]$text) {
    try {
        Add-Content -Path (Join-Path $root 'build\launcher_trace.txt') `
            -Value ('{0:yyyy-MM-dd HH:mm:ss} {1}' -f (Get-Date), $text)
    } catch { }
}

# The services answer /health; the site answers / with its page, so the path the
# probe asks for is a parameter rather than assumed.
function Answers([int]$port, [string]$path = '/health') {
    # Twenty seconds, not three. While the model is being loaded onto the card the
    # machine is busy enough that a three-second probe times out, and calling a
    # healthy-but-loading service "down" is what made the watchdog start a rival
    # copy at 21:32 on 13 Nov: the new one could not bind, the warm restarted, and
    # the AI took another five minutes to appear.
    $code = & curl.exe -s -o NUL -w '%{http_code}' --max-time 20 "http://127.0.0.1:$port$path"
    return ($code -eq '200')
}

# Health only answers once Flask is listening, which for the song service is
# after torch imports - about 40 s. Probing alone therefore says "not running"
# during exactly the window a second click lands in, and the second click used
# to start a second copy that then failed to bind 8090. Asking whether the
# process exists covers that window: one launcher run, one service.
#
# The marker has to be an argument, not a path. A venv's python.exe re-execs the
# interpreter named in its pyvenv.cfg, so the process that ends up owning the
# port reports the base uv python on its command line - no "song_service" and no
# ".venv" in it at all. Matching the folder therefore found nothing, every click
# started another copy, and each new copy spent forty seconds importing torch
# before failing to bind. "--role song" survives the re-exec and cannot be
# confused with the other two, which are all also called app.py.
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
    } elseif (Starting '*--role downloader*') {
    Say 'downloader is still starting, leaving it alone'
} else {
    $service = Join-Path $root 'downloader_service'
    $python = Join-Path $service '.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) {
        Say 'downloader: creating its environment (a minute or two)'
        $venvDir = Join-Path $service '.venv'
        $venvLog = Join-Path $root 'build\downloader_venv.log'
        # `python` on PATH on this machine is the Microsoft Store stub, which only
        # prints "Python was not found". Building the venv by its bare name
        # therefore failed silently and left a service that never started, so try
        # each interpreter that is actually here. `uv venv --seed` matters: without
        # --seed there is no pip in the venv and the install below cannot run.
        #
        # The preference is relaxed around these calls on purpose: uv and py write
        # progress to stderr, and under this script's Stop preference a native
        # command's stderr becomes a terminating error that aborted the whole
        # launcher on the first try - before the site or the tunnel were reached.
        $previous = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            if (Get-Command uv -ErrorAction SilentlyContinue) {
                & uv venv $venvDir --python 3.11 --seed *> $venvLog
            }
            if (-not (Test-Path $python) -and (Get-Command py -ErrorAction SilentlyContinue)) {
                & py -3.11 -m venv $venvDir *>> $venvLog
            }
            if (-not (Test-Path $python)) {
                & python -m venv $venvDir *>> $venvLog
            }
        } catch {
            Say "downloader: building its environment failed: $($_.Exception.Message)"
        } finally {
            $ErrorActionPreference = $previous
        }
        if (-not (Test-Path $python)) {
            Say "downloader: no Python could build its environment (see build\downloader_venv.log)"
        }
    }
    if (-not (Test-Path $python)) {
        Say 'downloader: not started for that reason'
    } else {
        if (-not (Get-ChildItem (Join-Path $service '.venv\Lib\site-packages') -Filter 'flask*' -ErrorAction SilentlyContinue)) {
            Say 'downloader: installing its packages'
            $previous = $ErrorActionPreference
            $ErrorActionPreference = 'Continue'
            try {
                & $python -m pip install -q --disable-pip-version-check -r (Join-Path $service 'requirements.txt') *>> $venvLog
            } catch {
                Say "downloader: installing its packages failed: $($_.Exception.Message)"
            } finally {
                $ErrorActionPreference = $previous
            }
        }
        $env:PORT = "$DownloadPort"
        Start-Process -FilePath $python -ArgumentList 'app.py', '--role', 'downloader' -WorkingDirectory $service `
            -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $root 'build\downloader_out.log') `
            -RedirectStandardError (Join-Path $root 'build\downloader_err.log') | Out-Null
        Say "downloader starting on 127.0.0.1:$DownloadPort (log: build\downloader_err.log)"
    }
}

# --- song service, on CUDA ----------------------------------------------
if (Answers $SongPort) {
    Say "song service already on 127.0.0.1:$SongPort"
    } elseif (Starting '*--role song*') {
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
    $songProc = Start-Process -FilePath $python -ArgumentList 'app.py', '--role', 'song' -WorkingDirectory $service `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $service 'logs\service_out.log') `
        -RedirectStandardError (Join-Path $service 'logs\service_err.log') -PassThru
    # Above normal: the first five minutes after a boot are a race between torch
    # importing, the 3.5B weights being paged onto the card and the site fitting
    # its own models over 12 000 videos. Without this the warm is what loses that
    # race, and the model takes several minutes longer to be usable.
    try { $songProc.PriorityClass = 'AboveNormal' } catch { }
    Say "song service starting on 127.0.0.1:$SongPort, warming CUDA (log: song_service\logs\service_out.log)"
}

# --- the site -------------------------------------------------------------
# app.py is the page itself, and it is the one process whose absence is noticed
# first, so it is started here with the two AI services rather than by hand.
# The marker is this root's venv python: every service is called app.py, so the
# name alone would match all three.
$sitePython = Join-Path $root '.venv\Scripts\python.exe'
$siteMarker = '*--role site*'

if (Answers $WebPort '/') {
    Say "site already on 127.0.0.1:$WebPort"
} elseif (Starting $siteMarker) {
    Say 'site is still starting, leaving it alone'
} elseif (-not (Test-Path $sitePython)) {
    Say "site: $sitePython is missing (create it with python -m venv .venv)"
} else {
    $env:PORT = "$WebPort"
    Start-Process -FilePath $sitePython -ArgumentList 'app.py', '--role', 'site' -WorkingDirectory $root `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $root 'run_web.log') `
        -RedirectStandardError (Join-Path $root 'run_web.err') | Out-Null
    Say "site starting on 127.0.0.1:$WebPort (log: run_web.log)"
}

# --- the tunnel -------------------------------------------------------------
# A Quick Tunnel gives the model an https address the internet can reach, which
# is what a phone on mobile data needs. Its name changes on every start, so the
# address is written to build\tunnel_url.txt and published to the site: the page
# reads it from there, and nobody pastes a new one into each device.
$cloudflared = Join-Path $root 'tools\bin\cloudflared.exe'
$tunnelLog = Join-Path $root 'tunnel.log'
$siteUrl = 'https://browser.bpiersing.workers.dev'

# A fresh clone has no cloudflared.exe: it is a 55 MB binary and gitignored, so
# "clone, run, the phone works" used to need a manual download first. Fetch it
# once, at a pinned version, and only run it if Windows calls the signature valid
# and names Cloudflare - a download straight into an executed path is not
# something to do on trust. "latest" is deliberately not used: that is a moving
# target nobody reviewing this script can check.
$cloudflaredVersion = '2026.10.7'
$cloudflaredUrl = "https://github.com/cloudflare/cloudflared/releases/download/$cloudflaredVersion/cloudflared-windows-amd64.exe"

function Get-Cloudflared([string]$target) {
    $partial = "$target.download"
    try {
        Say "tunnel: cloudflared is missing, fetching $cloudflaredVersion (~55 MB, once)"
        # Progress off: this runs under a hidden window at logon, and the progress
        # bar makes Invoke-WebRequest several times slower for no benefit.
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $cloudflaredUrl -OutFile $partial -UseBasicParsing -TimeoutSec 300

        $signature = Get-AuthenticodeSignature -FilePath $partial
        $signer = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { '' }
        if ($signature.Status -ne 'Valid' -or $signer -notmatch 'Cloudflare') {
            Say "tunnel: the download failed its signature check (status $($signature.Status)), so it was discarded"
            Remove-Item $partial -ErrorAction SilentlyContinue
            return $false
        }

        Move-Item -Path $partial -Destination $target -Force
        Say "tunnel: cloudflared $cloudflaredVersion in place"
        return $true
    } catch {
        Say "tunnel: could not fetch cloudflared ($($_.Exception.Message)); the model stays on this network"
        Remove-Item $partial -ErrorAction SilentlyContinue
        return $false
    }
}

if ($NoTunnel) {
    Say 'tunnel: skipped (-NoTunnel)'
} elseif (-not (Test-Path $cloudflared) -and -not (Get-Cloudflared $cloudflared)) {
    Say 'tunnel: cloudflared is missing, so the model stays on this network'
} else {
    $live = @(Get-Process cloudflared -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $cloudflared })
    if ($live.Count -gt 0) {
        Say 'tunnel: already running'
    } else {
        Remove-Item $tunnelLog -ErrorAction SilentlyContinue
        Start-Process -FilePath $cloudflared -WorkingDirectory $root -ArgumentList @(
            'tunnel', '--config', 'tools\bin\quick-tunnel.yml',
            '--url', 'http://127.0.0.1:8090', '--no-autoupdate',
            '--logfile', 'tunnel.log', '--loglevel', 'info'
        ) -WindowStyle Hidden | Out-Null
        Say 'tunnel: starting'
    }

    # The address reaches the log either way: a fresh tunnel writes it as it
    # connects, and one already up wrote it when it started.
    $tunnelUrl = ''
    for ($t = 0; $t -lt 20; $t++) {
        if (Test-Path $tunnelLog) {
            $tunnelUrl = (Select-String -Path $tunnelLog -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' |
                ForEach-Object { $_.Matches[0].Value } | Select-Object -Last 1)
            if ($tunnelUrl) { break }
        }
        Start-Sleep -Seconds 2
    }

    if (-not $tunnelUrl) {
        Say 'tunnel: no address yet, see tunnel.log'
    } else {
        try { Set-Content -Path (Join-Path $root 'build\tunnel_url.txt') -Value $tunnelUrl -Encoding ascii } catch { }
        try { Set-Clipboard -Value $tunnelUrl } catch { }
        Say "tunnel: $tunnelUrl"

        $keyFile = Join-Path $root 'build\song_endpoint.key'
        if (Test-Path $keyFile) {
            $key = (Get-Content $keyFile -Raw).Trim()
            if ($key) {
                # The JSON goes through a file: curl.exe on Windows mangles quotes
                # that arrive inside an argument, and the site answered "expected
                # JSON" while the address looked perfectly fine on screen.
                $payload = Join-Path $root 'build\tunnel_publish.json'
                try {
                    Set-Content -Path $payload -Encoding ascii `
                        -Value ('{"url":"' + $tunnelUrl + '"}')
                    $answer = & curl.exe -s --max-time 15 -X POST "$siteUrl/api/song/endpoint" `
                        -H 'Content-Type: application/json' -H "x-song-key: $key" `
                        --data-binary "@$payload"
                    Say "tunnel: published to the site: $answer"
                } finally {
                    Remove-Item $payload -ErrorAction SilentlyContinue
                }
            }
        } else {
            Say 'tunnel: build\song_endpoint.key is missing, so the site was not told the address'
        }
    }
}

$songHealth = & curl.exe -s --max-time 20 "http://127.0.0.1:$SongPort/health"
if ($songHealth) { Say "song now: $songHealth" } else { Say 'song: still loading, check again in a minute' }

# --- watchdog ------------------------------------------------------------
# Only one watchdog should exist: two would fight over the same 8090 and each
# would restart a service the other had just started.
function Watchers {
    Get-CimInstance Win32_Process -Filter "Name like '%powershell%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*start_services.ps1*' -and $_.CommandLine -like '*-Watch*' -and $_.ProcessId -ne $PID }
}

if ($Watch) {
    $others = @(Watchers)
    if ($others.Count -gt 0) {
        Trace "watchdog already running (pid $($others[0].ProcessId)), not adding another"
        Say 'watchdog already running'
        return
    }

    Trace 'watchdog started'
    Say 'watching all three services every 2 minutes'

    while ($true) {
        Start-Sleep -Seconds 120

        # A service that is answering needs nothing. One whose process exists but
        # is not answering is still importing torch or waiting on the model, so
        # it is left alone; only a port with no process behind it is restarted.
        $down = @()
        if (-not (Answers $WebPort '/') -and -not (Starting $siteMarker)) { $down += 'site' }
        if (-not $NoTunnel -and -not @(Get-Process cloudflared -ErrorAction SilentlyContinue).Count) { $down += 'tunnel' }
        if (-not (Answers $DownloadPort) -and -not (Starting '*--role downloader*')) { $down += 'downloader' }
        if (-not (Answers $SongPort) -and -not (Starting '*--role song*')) { $down += 'song service' }

        if ($down.Count -gt 0) {
            $which = $down -join ' and '
            Trace "watchdog: $which down, restarting"
            Say "$which down, restarting"
            Start-Process -FilePath 'powershell' -WindowStyle Hidden -ArgumentList @(
                '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath, '-Quiet'
            ) | Out-Null
        }
    }
}
