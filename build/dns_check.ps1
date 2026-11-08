Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
'--- dns ---'
nslookup learners-rail-secondary-benefit.trycloudflare.com 2>&1 | Out-String
'--- body ---'
& curl.exe -s --max-time 20 https://learners-rail-secondary-benefit.trycloudflare.com/health | Select-Object -First 8
'--- wrangler auth ---'
& npx --yes wrangler whoami 2>&1 | Select-Object -Last 8
