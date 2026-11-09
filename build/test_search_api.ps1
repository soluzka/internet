Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

function Try-Search([string]$label, [string]$url) {
    "=== $label ==="
    $raw = & curl.exe -s --max-time 30 $url
    try {
        $doc = $raw | ConvertFrom-Json
        "query: '$($doc.query)'  total: $($doc.total)  returned: $($doc.videos.Count)"
        "library: $($doc.library.total_videos) videos, $($doc.library.total_searches) searches, $($doc.library.total_clicks) clicks"
        $doc.videos | Select-Object -First 3 | ForEach-Object { "  - $($_.t)  ($($_.s), clicks $($_.c))" }
        if ($doc.error) { "error: $($doc.error)" }
    } catch {
        "not JSON: $($raw.Substring(0, [Math]::Min(300, $raw.Length)))"
    }
    ''
}

Try-Search 'one word' 'https://browser.bpiersing.workers.dev/api/search?q=dubstep'
Try-Search 'two words' 'https://browser.bpiersing.workers.dev/api/search?q=dubstep+mix&limit=5'
Try-Search 'nothing' 'https://browser.bpiersing.workers.dev/api/search?q=zzzznotathing'
Try-Search 'empty query' 'https://browser.bpiersing.workers.dev/api/search?q='
Try-Search 'logged search' 'https://browser.bpiersing.workers.dev/api/search?q=pizza&log=1&limit=3'
