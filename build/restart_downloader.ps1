Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

# Every earlier restart left a live instance behind: the venv python re-execs a
# base python, so stopping only the pid netstat reported left the child serving
# old code on 8080. Kill each downloader process and its children.
$all = Get-CimInstance Win32_Process -Filter "Name='python.exe'"
$downloader = $all | Where-Object { $_.CommandLine -like '*downloader_service*' -and $_.CommandLine -like '*app.py*' }
$ids = @($downloader | ForEach-Object { [int]$_.ProcessId })
foreach ($parent in $ids) {
    $kids = @($all | Where-Object { $_.ParentProcessId -eq $parent } | ForEach-Object { [int]$_.ProcessId })
    foreach ($kid in $kids) { if ($ids -notcontains $kid) { $ids += $kid } }
}
"stopping: $($ids -join ',')"
foreach ($id in $ids) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 3

$left = netstat -ano | Select-String ':8080\s' | Select-String 'LISTENING'
if ($left) { "STILL LISTENING: $left" } else { 'port 8080 free' }

$env:PORT = '8080'
Start-Process -FilePath 'D:\scrape_videos\scrape_videos\scrape\scrape\my_app\scrape\downloader_service\.venv\Scripts\python.exe' `
    -ArgumentList 'app.py' -WorkingDirectory 'D:\scrape_videos\scrape_videos\scrape\scrape\my_app\scrape\downloader_service' `
    -WindowStyle Hidden -RedirectStandardOutput 'D:\scrape_videos\scrape_videos\scrape\scrape\my_app\scrape\build\downloader_out.log' `
    -RedirectStandardError 'D:\scrape_videos\scrape_videos\scrape\scrape\my_app\scrape\build\downloader_err.log' | Out-Null

for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 700
    $code = & curl.exe -s -o NUL -w '%{http_code}' --max-time 3 'http://127.0.0.1:8080/health'
    if ($code -eq '200') { break }
}

'--- discover ---'
& curl.exe -s --max-time 60 -X POST 'http://127.0.0.1:8080/api/discover' -H 'Content-Type: application/json' -d '{"query":"dubstep mix","limit":2}'
