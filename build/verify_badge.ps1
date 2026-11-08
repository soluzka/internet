Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
$page = (& curl.exe -s --max-time 25 https://browser.bpiersing.workers.dev/) -join "`n"
$needle = "ON_LOCAL_APP ? 'connecting' : 'snapshot'"
Write-Host ("deployed page has the conditional badge state: " + $page.Contains($needle))
Write-Host ("page bytes: " + $page.Length)
