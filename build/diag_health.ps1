Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

'--- health 8090 ---'
& curl.exe -s --max-time 8 http://127.0.0.1:8090/health
''
'--- health 8080 ---'
& curl.exe -s --max-time 8 http://127.0.0.1:8080/health
''
'--- downloader err (tail) ---'
if (Test-Path build/downloader_err.log) { Get-Content build/downloader_err.log -Tail 12 }
''
'--- who owns the listening sockets ---'
foreach ($p in 8080, 8090) {
    $conns = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
        "$p pid $($c.OwningProcess) $($proc.ProcessName) started $($proc.StartTime)"
    }
}
