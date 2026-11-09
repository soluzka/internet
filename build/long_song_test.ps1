Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

'--- restart so the new limits are loaded ---'
@(Get-CimInstance Win32_Process -Filter "Name like '%python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*song_service*' }) | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 3
& powershell -NoProfile -ExecutionPolicy Bypass -File tools/start_services.ps1 -Quiet

'--- wait for the service to answer ---'
$sw = [Diagnostics.Stopwatch]::StartNew()
while ($sw.Elapsed.TotalSeconds -lt 180) {
    $code = & curl.exe -s -o NUL -w '%{http_code}' --max-time 5 'http://127.0.0.1:8090/health'
    if ($code -eq '200') { break }
    Start-Sleep -Seconds 5
}
"health after $([int]$sw.Elapsed.TotalSeconds)s"

'--- lyrics ---'
$lyricReq = Join-Path $env:TEMP 'long_lyrics_req.json'
Set-Content -Path $lyricReq -Value '{"genre":"synthwave","seed":777,"avoid":[]}' -Encoding ascii
$sw = [Diagnostics.Stopwatch]::StartNew()
& curl.exe -s -o "$env:TEMP\long_lyrics.json" --max-time 300 -X POST 'http://127.0.0.1:8090/api/lyrics' `
    -H 'Content-Type: application/json' --data-binary "@$lyricReq" | Out-Null
"lyrics in $([math]::Round($sw.Elapsed.TotalSeconds,1))s"

$lyrics = Get-Content "$env:TEMP\long_lyrics.json" -Raw | ConvertFrom-Json
$lineCount = ($lyrics.sections | ForEach-Object { $_.lines.Count } | Measure-Object -Sum).Sum
"sections: $($lyrics.sections.Count)   lines: $lineCount"
$lyrics.sections | ForEach-Object { "  {0,-12} {1} lines" -f $_.section, $_.lines.Count }
$text = ($lyrics.sections | ForEach-Object { ($_.lines -join "`n") }) -join "`n`n"

'--- queue 180 s / 24 steps ---'
$payload = @{
    prompt  = 'synthwave song, 100 bpm, warm analog production, mastered, wide stereo, clear emotional lead vocal, arrangement in layers: warm pad underneath, arpeggiated synth counter-melody, backing harmonies answering the lead, programmed percussion patterns that change between sections, bass line that moves under the chorus'
    lyrics  = $text
    seconds = 180
    steps   = 24
}
$songReq = Join-Path $env:TEMP 'long_song_req.json'
$payload | ConvertTo-Json -Compress | Set-Content -Path $songReq -Encoding utf8
& curl.exe -s -o "$env:TEMP\long_queue.json" --max-time 60 -X POST 'http://127.0.0.1:8090/api/song' `
    -H 'Content-Type: application/json' --data-binary "@$songReq" | Out-Null
$queued = Get-Content "$env:TEMP\long_queue.json" -Raw | ConvertFrom-Json
"token $($queued.token)  seconds $($queued.seconds)  steps $($queued.steps)"
if (-not $queued.token) { 'queueing failed'; exit 1 }

'--- wait for the render ---'
$sw = [Diagnostics.Stopwatch]::StartNew()
while ($sw.Elapsed.TotalSeconds -lt 900) {
    $job = & curl.exe -s --max-time 10 "http://127.0.0.1:8090/api/song/$($queued.token)" | ConvertFrom-Json
    if ($job.status -in @('complete', 'error')) { break }
    Start-Sleep -Seconds 5
}
"render: $($job.status) in $([math]::Round($sw.Elapsed.TotalSeconds,1))s"

if ($job.status -eq 'complete') {
    & curl.exe -s -o "$env:TEMP\long_song.wav" --max-time 300 "http://127.0.0.1:8090/song_file/$($queued.token)" | Out-Null
    $info = & song_service\.venv\Scripts\python.exe -c "import wave,sys; w=wave.open(sys.argv[1]); print(round(w.getnframes()/w.getframerate(),2))" "$env:TEMP\long_song.wav"
    "audio length: $info s"
    "size: $([math]::Round((Get-Item "$env:TEMP\long_song.wav").Length/1MB,1)) MB"
} else {
    "error: $($job.error)"
}
