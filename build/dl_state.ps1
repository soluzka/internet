Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
'--- app on 5001 ---'
& curl.exe -s -o NUL -w 'api/stats: %{http_code}' --max-time 5 http://127.0.0.1:5001/api/stats
''
'--- ai_engine processes ---'
Get-Process ai_engine -ErrorAction SilentlyContinue | Select-Object Id, StartTime | Format-Table -AutoSize | Out-String
'--- POST /api/download with a fake id ---'
& curl.exe -s -X POST 'http://127.0.0.1:5001/api/download' -H 'Content-Type: application/json' -H 'Origin: https://browser.bpiersing.workers.dev' --data '{"url":"https://www.youtube.com/watch?v=notarealid"}' --max-time 15
''
'--- CORS headers the page would see ---'
& curl.exe -s -o NUL -D - -X POST 'http://127.0.0.1:5001/api/download' -H 'Content-Type: application/json' -H 'Origin: https://browser.bpiersing.workers.dev' --data '{"url":"https://www.youtube.com/watch?v=notarealid"}' --max-time 15 | Select-String 'access-control|HTTP/'
