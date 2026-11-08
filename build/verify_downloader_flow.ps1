Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
New-Item -ItemType Directory -Force -Path build | Out-Null
& powershell -NoProfile -ExecutionPolicy Bypass -File tools/start_downloader.ps1 -Hidden
''
'--- health ---'
& curl.exe -s --max-time 8 http://127.0.0.1:8080/health
''
'--- cross-origin POST as the deployed page would send it ---'
& curl.exe -s -o NUL -D - -X POST 'http://127.0.0.1:8080/api/download' `
    -H 'Content-Type: application/json' -H 'Origin: https://browser.bpiersing.workers.dev' `
    --data '{"url":"https://www.youtube.com/watch?v=notarealid"}' --max-time 20 |
    Select-String 'HTTP/|access-control-allow-origin'
& curl.exe -s -X POST 'http://127.0.0.1:8080/api/download' `
    -H 'Content-Type: application/json' -H 'Origin: https://browser.bpiersing.workers.dev' `
    --data '{"url":"https://www.youtube.com/watch?v=notarealid"}' --max-time 20
''
'--- memory used ---'
Get-Process python -ErrorAction SilentlyContinue |
    Select-Object Id, @{n='MB';e={[math]::Round($_.WorkingSet64/1MB)}} | Format-Table -AutoSize | Out-String
