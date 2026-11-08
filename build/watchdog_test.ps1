Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

'--- watchdog running? ---'
$watch = @(Get-CimInstance Win32_Process -Filter "Name like '%powershell%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*start_services.ps1*' -and $_.CommandLine -like '*-Watch*' })
foreach ($w in $watch) { "pid $($w.ProcessId)  started $($w.CreationDate)" }
"count: $($watch.Count)"

'--- song service pids before kill ---'
$song = @(Get-CimInstance Win32_Process -Filter "Name like '%python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*song_service*' })
foreach ($p in $song) { "pid $($p.ProcessId)  $([math]::Round($p.WorkingSetSize/1MB)) MB" }

if ($song.Count -eq 0) { 'nothing to kill, aborting test'; exit 1 }

'--- killing them ---'
foreach ($p in $song) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2
$code = & curl.exe -s -o NUL -w '%{http_code}' --max-time 3 'http://127.0.0.1:8090/health'
"8090 right after kill: $code"

'--- waiting up to 4 minutes for the watchdog ---'
$sw = [Diagnostics.Stopwatch]::StartNew()
$back = $false
while ($sw.Elapsed.TotalSeconds -lt 240) {
    Start-Sleep -Seconds 5
    $code = & curl.exe -s -o NUL -w '%{http_code}' --max-time 3 'http://127.0.0.1:8090/health'
    if ($code -eq '200') { $back = $true; break }
    if ([int]($sw.Elapsed.TotalSeconds) % 30 -lt 5) { "  t+$([int]$sw.Elapsed.TotalSeconds)s: $code" }
}

if ($back) { "8090 answering again after $([int]$sw.Elapsed.TotalSeconds) s" } else { '8090 did not come back within 4 minutes' }

'--- launcher trace ---'
Get-Content build\launcher_trace.txt -Tail 8
