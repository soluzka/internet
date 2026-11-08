# Cold start: nothing running, exe launched, song queued at once. This mirrors a
# user clicking "make a song" right after opening the app.
$ErrorActionPreference = 'Continue'
$root = 'D:\scrape_videos\scrape_videos\scrape\scrape\my_app\scrape'
$work = Join-Path $root 'build'
$exe = Join-Path $root 'dist\ai_engine.exe'
$port = 5095

Get-Process ai_engine -ErrorAction SilentlyContinue | Stop-Process -Force
$listener = (Get-NetTCPConnection -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue).OwningProcess
if ($listener) { Stop-Process -Id $listener -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 3

$payload = Join-Path $work 'song_payload.json'
@{ prompt = 'warm analog electronic beat, sung male vocal, mastered'
   lyrics = "[Verse]`nRain on the steel`nCold water holds the light`n[Chorus]`nHold the water, hold the night"
   seconds = 30
   steps = 12 } | ConvertTo-Json | Set-Content -Path $payload -Encoding utf8

$env:PORT = "$port"
$out = Join-Path $work 'e2e2.out.log'
$err = Join-Path $work 'e2e2.err.log'
$proc = Start-Process -FilePath $exe -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $out -RedirectStandardError $err

$sw = [Diagnostics.Stopwatch]::StartNew()
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    if ($proc.HasExited) { break }
    try {
        if ((Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/" -TimeoutSec 4).StatusCode -eq 200) {
            $ready = $true
            break
        }
    } catch { }
}
if (-not $ready) { 'exe never answered'; exit 1 }
"page ready after $([int]$sw.Elapsed.TotalSeconds)s"

$body = Get-Content $payload -Raw
$answer = & curl.exe -s -S -m 240 -w "`nqueued in %{time_total}s http %{http_code}" `
    -X POST -H 'Content-Type: application/json' --data-binary $body `
    "http://127.0.0.1:$port/api/song"
"$answer"

$token = $null
try { $token = ($answer -split "`n")[0] | ConvertFrom-Json | Select-Object -ExpandProperty token } catch { }
if (-not $token) { 'no token, so the job was never queued'; }
else {
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 10
        $status = & curl.exe -s -m 20 "http://127.0.0.1:$port/api/song/$token"
        "status: $status"
        if ($status -match '"status"\s*:\s*"(complete|done|error|failed)"') { break }
    }
    $file = Join-Path $work 'e2e2_song.wav'
    & curl.exe -s -o $file -w 'download: http %{http_code}, %{size_download} bytes' `
        "http://127.0.0.1:$port/song_file/$token"
    ''
}

'--- exe log ---'
Get-Content $out, $err -ErrorAction SilentlyContinue |
    Where-Object { $_ -match 'AI|song_service|Warming|Starting|error' } |
    Select-Object -Last 6

if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
"stopped exe pid $($proc.Id)"
