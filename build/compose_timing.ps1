Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

$t0 = Get-Date
function Stamp { param($label) '{0,7:N1}s  {1}' -f ((Get-Date) - $t0).TotalSeconds, $label }

'--- health before ---'
$health = & curl.exe -s --max-time 5 'http://127.0.0.1:8090/health'
$health

# --- 1. lyrics -----------------------------------------------------------
$lyricReq = Join-Path $env:TEMP 'c_lyrics_req.json'
Set-Content -Path $lyricReq -Value '{"genre":"synthwave","seed":4242,"avoid":[]}' -Encoding ascii

$sw = [Diagnostics.Stopwatch]::StartNew()
& curl.exe -s -o "$env:TEMP\c_lyrics.json" --max-time 300 -X POST 'http://127.0.0.1:8090/api/lyrics' `
    -H 'Content-Type: application/json' --data-binary "@$lyricReq" | Out-Null
$lyricSeconds = $sw.Elapsed.TotalSeconds
Stamp ("lyrics done in {0:N1}s" -f $lyricSeconds)

$raw = Get-Content "$env:TEMP\c_lyrics.json" -Raw
$lyrics = $null
try { $lyrics = $raw | ConvertFrom-Json } catch { }
if (-not $lyrics -or -not $lyrics.sections) {
    'lyrics request failed, response was:'
    $raw.Substring(0, [Math]::Min(400, $raw.Length))
    exit 1
}
$text = ($lyrics.sections | ForEach-Object { ($_.lines -join "`n") }) -join "`n`n"
"model: $($lyrics.model)"
"lines: $(($lyrics.sections | ForEach-Object { $_.lines.Count } | Measure-Object -Sum).Sum)"
''

# --- 2. queue the render -------------------------------------------------
$payload = @{
    prompt  = 'synthwave song, 100 bpm, warm analog production, mastered, clear emotional lead vocal'
    lyrics  = $text
    seconds = 90
    steps   = 16
}
$songReq = Join-Path $env:TEMP 'c_song_req.json'
$payload | ConvertTo-Json -Compress | Set-Content -Path $songReq -Encoding utf8

$sw = [Diagnostics.Stopwatch]::StartNew()
& curl.exe -s -o "$env:TEMP\c_queue.json" --max-time 60 -X POST 'http://127.0.0.1:8090/api/song' `
    -H 'Content-Type: application/json' --data-binary "@$songReq" | Out-Null
$queueSeconds = $sw.Elapsed.TotalSeconds
Stamp ("queued in {0:N1}s" -f $queueSeconds)

$queueRaw = Get-Content "$env:TEMP\c_queue.json" -Raw
$queued = $null
try { $queued = $queueRaw | ConvertFrom-Json } catch { }
if (-not $queued -or -not $queued.token) {
    'queueing failed, response was:'
    $queueRaw.Substring(0, [Math]::Min(400, $queueRaw.Length))
    exit 1
}
"token: $($queued.token)  status: $($queued.status)  reused: $($queued.reused)"
$token = $queued.token
''

# --- 3. poll until complete ---------------------------------------------
$sw = [Diagnostics.Stopwatch]::StartNew()
$lastStatus = ''
$stages = @{}
$job = $null
while ($sw.Elapsed.TotalSeconds -lt 900) {
    $job = & curl.exe -s --max-time 10 "http://127.0.0.1:8090/api/song/$token" | ConvertFrom-Json
    if ($job.status -ne $lastStatus) {
        $stages[$job.status] = [math]::Round($sw.Elapsed.TotalSeconds, 1)
        Stamp ("status -> {0}  ({1}% of the job, {2}s since it was created)" -f $job.status,
            [math]::Round([double]$job.progress * 100), $job.elapsed)
        $lastStatus = $job.status
    }
    if ($job.status -in @('complete', 'error')) { break }
    Start-Sleep -Seconds 3
}
$renderSeconds = $sw.Elapsed.TotalSeconds
''

# --- 4. download the audio ----------------------------------------------
$dlSeconds = 0
if ($lastStatus -eq 'complete') {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    & curl.exe -s -o "$env:TEMP\c_song.wav" --max-time 300 "http://127.0.0.1:8090/song_file/$token" | Out-Null
    $dlSeconds = $sw.Elapsed.TotalSeconds
    $size = if (Test-Path "$env:TEMP\c_song.wav") { (Get-Item "$env:TEMP\c_song.wav").Length } else { 0 }
    Stamp ("audio downloaded in {0:N1}s ({1:N1} MB)" -f $dlSeconds, ($size / 1MB))
} else {
    "job ended as $lastStatus"
    if ($job -and $job.error) { "error: $($job.error)" }
}
''

'================ timings ================'
'lyrics                {0,7:N1}s' -f $lyricSeconds
'queue (accepted)      {0,7:N1}s' -f $queueSeconds
'render                {0,7:N1}s' -f $renderSeconds
if ($dlSeconds) { 'download              {0,7:N1}s' -f $dlSeconds }
if ($dlSeconds) { 'TOTAL                 {0,7:N1}s' -f ($lyricSeconds + $queueSeconds + $renderSeconds + $dlSeconds) }
''
'status reached at (s from POST /api/song):'
$stages.GetEnumerator() | Sort-Object Value | ForEach-Object { '  {0,-12} {1,7:N1}' -f $_.Key, $_.Value }
''

'================ service log ================'
Get-Content song_service\logs\service_out.log -Tail 25
