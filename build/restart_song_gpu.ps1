Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

# Stop only the process serving 8090.
$line = netstat -ano | Select-String ':8090\s' | Select-String 'LISTENING' | Select-Object -First 1
if ($line) {
    $owner = ($line.Line -split '\s+')[-1]
    "stopping song service pid $owner"
    Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
}

$py = Join-Path (Get-Location) 'song_service\.venv\Scripts\python.exe'
$env:SONG_PORT = '8090'
Start-Process -FilePath $py -ArgumentList 'app.py' -WorkingDirectory (Join-Path (Get-Location) 'song_service') `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path (Get-Location) 'song_service\logs\service_out.log') `
    -RedirectStandardError (Join-Path (Get-Location) 'song_service\logs\service_err.log') | Out-Null

for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 2
    $code = & curl.exe -s -o NUL -w '%{http_code}' --max-time 4 http://127.0.0.1:8090/health
    if ($code -eq '200') { "health after $((($i + 1) * 2))s"; break }
}
