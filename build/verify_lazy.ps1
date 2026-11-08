Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
$page = (& curl.exe -s --max-time 25 https://browser.bpiersing.workers.dev/) -join "`n"
"contains ensureSocket: $($page.Contains('async function ensureSocket'))"
"contains autoConnect:  $($page.Contains('autoConnect: ON_LOCAL_APP'))"
"contains doSearch await: $($page.Contains('await ensureSocket()'))"
"still has the old probe on load: $($page.Contains("fetchBounded(LOCAL_APP + '/api/stats', {}, 2500).then"))"
