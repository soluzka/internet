# End-to-end through the exe: page, lyrics, render. Logs both sides so a failure
# is visible instead of guessed at.
$ErrorActionPreference = 'Continue'
$root = 'D:\scrape_videos\scrape_videos\scrape\scrape\my_app\scrape'
$work = Join-Path $root 'build'
$exe = Join-Path $root 'dist\ai_engine.exe'

Get-Process ai_engine -ErrorAction SilentlyContinue | Stop-Process -Force
$listener = (Get-NetTCPConnection -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue).OwningProcess
if ($listener) {
    Stop-Process -Id $listener -Force -ErrorAction SilentlyContinue
    "stopped the old service on 8090 (pid $listener)"
}
Start-Sleep -Seconds 3

$env:PORT = '5096'
$out = Join-Path $work 'e2e.out.log'
$err = Join-Path $work 'e2e.err.log'
$proc = Start-Process -FilePath $exe -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $out -RedirectStandardError $err

$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 2
    if ($proc.HasExited) { break }
    try {
        if ((Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5096/' -TimeoutSec 5).StatusCode -eq 200) {
            $ready = $true
            break
        }
    } catch { }
}
if (-not $ready) { 'exe never answered'; exit 1 }
'page: 200'

'--- lyrics (this starts the AI) ---'
& curl.exe -s -S -m 300 -X POST -H 'Content-Type: application/json' `
    -d '{"genre":"electronic music","subject":"rain on a steel roof"}' `
    http://127.0.0.1:5096/api/lyrics
''

'--- render, 8 seconds ---'
$start = & curl.exe -s -S -m 120 -X POST -H 'Content-Type: application/json' `
    -d '{"prompt":"warm electronic beat, sung vocals","lyrics":"[Verse]\nRain on steel\n[Chorus]\nHold the water","seconds":8,"steps":8}' `
    http://127.0.0.1:5096/api/song
"song start: $start"

$token = $null
try { $token = ($start | ConvertFrom-Json).token } catch { }
if ($token) {
    for ($i = 0; $i -lt 24; $i++) {
        Start-Sleep -Seconds 10
        $status = & curl.exe -s -m 20 "http://127.0.0.1:5096/api/song/$token"
        "status: $status"
        if ($status -match '"status"\s*:\s*"(done|error|failed)"') { break }
    }
    $file = Join-Path $work 'e2e_song.wav'
    & curl.exe -s -o $file -w 'file: HTTP %{http_code}, %{size_download} bytes' `
        "http://127.0.0.1:5096/song_file/$token"
    ''
} else {
    'no token came back, so nothing to poll'
}

'--- exe log ---'
Get-Content $out, $err -ErrorAction SilentlyContinue |
    Where-Object { $_ -match 'AI|song_service|Starting|error|Error' } |
    Select-Object -Last 8

'--- service log ---'
Get-Content (Join-Path $root 'song_service\logs\autostart.log') -Tail 8 -ErrorAction SilentlyContinue

if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
"stopped exe pid $($proc.Id)"
