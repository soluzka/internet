Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

$prompt = 'dubstep song, with touches of techno, 137 bpm, heavy and patient, all weight on the low end, half-time kick and snare, a wobbling sub that answers the vocal, granular riser, clipped rimshot fills, clean modern master, heavy sub bass, wobbling growl lead, big gated snare, clear emotional lead vocal, arrangement in layers: a chord bed underneath, a counter-melody answering the lead, backing harmonies, percussion patterns that change between sections, a bass line that moves under the chorus'

$lyricReq = Join-Path $env:TEMP 'dub_lyrics_req.json'
Set-Content -Path $lyricReq -Value '{"genre":"dubstep","seed":5150,"avoid":[]}' -Encoding ascii
& curl.exe -s -o "$env:TEMP\dub_lyrics.json" --max-time 300 -X POST 'http://127.0.0.1:8090/api/lyrics' `
    -H 'Content-Type: application/json' --data-binary "@$lyricReq" | Out-Null
$lyr = Get-Content "$env:TEMP\dub_lyrics.json" -Raw | ConvertFrom-Json
$text = ($lyr.sections | ForEach-Object { ($_.lines -join "`n") }) -join "`n`n"
"lyrics: $($lyr.sections.Count) sections, $(($lyr.sections | ForEach-Object { $_.lines.Count } | Measure-Object -Sum).Sum) lines"

$payload = @{ prompt = $prompt; lyrics = $text; seconds = 150; steps = 24 }
$req = Join-Path $env:TEMP 'dub_song_req.json'
$payload | ConvertTo-Json -Compress | Set-Content -Path $req -Encoding utf8
& curl.exe -s -o "$env:TEMP\dub_queue.json" --max-time 60 -X POST 'http://127.0.0.1:8090/api/song' `
    -H 'Content-Type: application/json' --data-binary "@$req" | Out-Null
$q = Get-Content "$env:TEMP\dub_queue.json" -Raw | ConvertFrom-Json
"queued seconds=$($q.seconds) steps=$($q.steps)"
if (-not $q.token) { 'queueing failed'; exit 1 }

$sw = [Diagnostics.Stopwatch]::StartNew()
while ($sw.Elapsed.TotalSeconds -lt 900) {
    $job = & curl.exe -s --max-time 10 "http://127.0.0.1:8090/api/song/$($q.token)" | ConvertFrom-Json
    if ($job.status -in @('complete', 'error')) { break }
    Start-Sleep -Seconds 5
}
"render $($job.status) in $([math]::Round($sw.Elapsed.TotalSeconds,1))s"
if ($job.status -eq 'complete') {
    & curl.exe -s -o "$env:TEMP\dub.wav" --max-time 300 "http://127.0.0.1:8090/song_file/$($q.token)" | Out-Null
    $secs = & song_service\.venv\Scripts\python.exe -c "import wave,sys; w=wave.open(sys.argv[1]); print(round(w.getnframes()/w.getframerate(),2))" "$env:TEMP\dub.wav"
    "audio: $secs s, $([math]::Round((Get-Item "$env:TEMP\dub.wav").Length/1MB,1)) MB"
} else {
    "error: $($job.error)"
}
