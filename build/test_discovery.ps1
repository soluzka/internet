Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

function Search([string]$q) {
    $raw = & curl.exe -s --max-time 60 "https://browser.bpiersing.workers.dev/api/search?q=$q&limit=5&discover=1&log=1"
    $doc = $raw | ConvertFrom-Json
    "q='$($doc.query)'  matches=$($doc.total)  discovered=$($doc.discovered)  library=$($doc.library.total_videos)  searches=$($doc.library.total_searches)"
    $doc.videos | Select-Object -First 2 | ForEach-Object { "   - $($_.t)  [$($_.du)]  $($_.th)" }
    ''
}

'--- before ---'
(S (curl.exe -s --max-time 20 'https://browser.bpiersing.workers.dev/api/search?q=') | ConvertFrom-Json).library | ConvertTo-Json -Compress
''

Search 'tractor pulling'
Search 'northern soul allnighter'
Search 'dubstep'
