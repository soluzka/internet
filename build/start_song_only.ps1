Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

$up = & curl.exe -s -o NUL -w '%{http_code}' --max-time 4 http://127.0.0.1:8090/health
if ($up -eq '200') {
    'the song service is already running'
} else {
    $py = Join-Path (Get-Location) 'song_service\.venv\Scripts\python.exe'
    $env:SONG_PORT = '8090'
    Start-Process -FilePath $py -ArgumentList 'app.py' -WorkingDirectory (Join-Path (Get-Location) 'song_service') `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path (Get-Location) 'song_service\logs\service_out.log') `
        -RedirectStandardError (Join-Path (Get-Location) 'song_service\logs\service_err.log') | Out-Null
    'started the song service'
}

for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 2
    $code = & curl.exe -s -o NUL -w '%{http_code}' --max-time 4 http://127.0.0.1:8090/health
    if ($code -eq '200') { "health answered after $((($i + 1) * 2))s"; break }
}
& curl.exe -s --max-time 6 http://127.0.0.1:8090/health
''
Get-Process python -ErrorAction SilentlyContinue |
    Select-Object Id, @{n='MB';e={[math]::Round($_.WorkingSet64/1MB)}} | Format-Table -AutoSize | Out-String
