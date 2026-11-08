Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
$base = 'https://browser.bpiersing.workers.dev'
foreach ($path in @('/api/lyrics', '/api/song', '/api/song/latest', '/api/health')) {
    $method = if ($path -eq '/api/song/latest' -or $path -eq '/api/health') { 'GET' } else { 'POST' }
    $out = & curl.exe -s -o NUL -w "%{http_code}" -X $method "$base$path" -H 'Content-Type: application/json' --data '{}' --max-time 15
    "{0,-22} {1,-4} -> {2}" -f $path, $method, $out
}
'--- body of /api/song ---'
& curl.exe -s -X POST "$base/api/song" -H 'Content-Type: application/json' --data '{}' --max-time 15
''
