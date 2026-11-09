Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

$tmp = Join-Path $env:TEMP 'live_index2.html'
& curl.exe -s --max-time 30 -o $tmp 'https://browser.bpiersing.workers.dev/'
$text = Get-Content $tmp -Raw

foreach ($m in @('edgeModelKnownOff', 'rememberEdgeModelOff', "localStorage.getItem('edgeModelOff')", 'window.appUnavailable) {')) {
    if ($text -like "*$m*") { "live: $m" } else { "MISSING: $m" }
}

'--- caching headers from the Worker ---'
& curl.exe -s -I --max-time 20 'https://browser.bpiersing.workers.dev/' | Select-String -Pattern 'cache-control|etag|age|last-modified'
