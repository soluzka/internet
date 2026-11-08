Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
$page = (& curl.exe -s --max-time 25 https://browser.bpiersing.workers.dev/) -join "`n"
"app-down message present: $($page.Contains('Voice search runs in the desktop app on this machine'))"
"unreachable detection:    $($page.Contains('failed to fetch|NetworkError|Load failed') -or $page.Contains('Failed to fetch|NetworkError|Load failed'))"
'--- is the app up? ---'
& curl.exe -s -o NUL -w 'api/stats: %{http_code}' --max-time 5 http://127.0.0.1:5001/api/stats
''
