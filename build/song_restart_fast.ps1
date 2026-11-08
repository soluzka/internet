Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

# Every song service process: the two pairs left by the earlier restarts.
$pids = @(376, 6460, 25240, 2792)
foreach ($id in $pids) {
    $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
    if ($proc) {
        "stopping $id ($([math]::Round($proc.WorkingSet64 / 1MB)) MB)"
        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Seconds 3
$left = & curl.exe -s -o NUL -w '%{http_code}' --max-time 3 http://127.0.0.1:8090/health
"8090 after stop: $left"

# Start one and return immediately; the service imports torch for ~20 s.
$py = Join-Path (Get-Location) 'song_service\.venv\Scripts\python.exe'
$env:SONG_PORT = '8090'
$new = Start-Process -FilePath $py -ArgumentList 'app.py' -WorkingDirectory (Join-Path (Get-Location) 'song_service') `
    -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path (Get-Location) 'song_service\logs\service_out.log') `
    -RedirectStandardError (Join-Path (Get-Location) 'song_service\logs\service_err.log')
"started pid $($new.Id) - give it twenty seconds"
