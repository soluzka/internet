Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

'--- job state before restart ---'
try { (Invoke-RestMethod 'http://127.0.0.1:8090/api/song/latest' -TimeoutSec 6) | ConvertTo-Json -Compress } catch { 'no job' }

# Only stop the service processes (the venv launcher and its child), not the app.
$svc = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*song_service*app.py*' -or $_.CommandLine -like '*app.py*' } |
    Where-Object { $_.ExecutablePath -like '*song_service\\.venv*' -or $_.ExecutablePath -like '*Python311*' }
foreach ($proc in $svc) {
    if ($proc.CommandLine -match 'app\.py' -and $proc.CommandLine -notmatch 'downloader') {
        "stopping $($proc.ProcessId): $($proc.CommandLine)"
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Seconds 3

$py = Join-Path (Get-Location) 'song_service\.venv\Scripts\python.exe'
$env:SONG_PORT = '8090'
Start-Process -FilePath $py -ArgumentList 'app.py' -WorkingDirectory (Join-Path (Get-Location) 'song_service') `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path (Get-Location) 'song_service\logs\restart_out.log') `
    -RedirectStandardError (Join-Path (Get-Location) 'song_service\logs\restart_err.log') | Out-Null
'started the song service'

for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 3
    try {
        $h = Invoke-RestMethod 'http://127.0.0.1:8090/health' -TimeoutSec 5
        if ($h.ok) { "health ok after $((($i + 1) * 3))s: loaded=$($h.loaded)"; break }
    } catch {}
}
