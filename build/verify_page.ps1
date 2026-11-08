Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
$page = & curl.exe -s --max-time 25 https://browser.bpiersing.workers.dev/
"page bytes: $($page.Length)"
$page | Select-String -Pattern 'LOCAL_APP|ON_LOCAL_APP' | ForEach-Object { $_.Line.Trim() }
& curl.exe -s -o NUL -w 'status: %{http_code}' --max-time 20 https://browser.bpiersing.workers.dev/
''
& curl.exe -s --max-time 20 https://browser.bpiersing.workers.dev/config.js | Select-String -Pattern 'DOWNLOAD_API =|SONG_API ='
