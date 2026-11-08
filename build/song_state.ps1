Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
& curl.exe -s --max-time 5 http://127.0.0.1:8090/health
''
& curl.exe -s -o NUL -w '8080: %{http_code}' --max-time 4 http://127.0.0.1:8080/health
''
Get-Process python -ErrorAction SilentlyContinue |
    Select-Object Id, StartTime, @{n='MB';e={[math]::Round($_.WorkingSet64/1MB)}} |
    Format-Table -AutoSize | Out-String
'--- worker answers for the song routes ---'
& curl.exe -s -o NUL -w 'POST /api/song: %{http_code}' -X POST 'https://browser.bpiersing.workers.dev/api/song' -H 'Content-Type: application/json' --data '{}' --max-time 15
''
& curl.exe -s -o NUL -w 'POST /api/lyrics: %{http_code}' -X POST 'https://browser.bpiersing.workers.dev/api/lyrics' -H 'Content-Type: application/json' --data '{}' --max-time 15
''
