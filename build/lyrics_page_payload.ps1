Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
$body = @{
    genre   = 'techno'
    subject = 'bass, night, city, rain'
    corpus  = @('night drive', 'city lights', 'rain on glass')
    angle   = 'a worker finishing a long shift'
    seed    = 4242
    avoid   = @()
} | ConvertTo-Json -Compress
$body | Set-Content 'build\lyrics_page_request.json' -Encoding ascii -NoNewline

$sw = [System.Diagnostics.Stopwatch]::StartNew()
$out = & curl.exe -s -X POST 'http://127.0.0.1:8090/api/lyrics' -H 'Content-Type: application/json' -H 'Origin: https://browser.bpiersing.workers.dev' --data-binary '@build/lyrics_page_request.json' --max-time 300
$sw.Stop()
"seconds: $([math]::Round($sw.Elapsed.TotalSeconds, 1))"
$parsed = $out | ConvertFrom-Json
"model: $($parsed.model)"
"sections: $($parsed.sections.Count)"
$parsed.sections | ForEach-Object { "  [$($_.section)] $($_.lines.Count) lines" }
