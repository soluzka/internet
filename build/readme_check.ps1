Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

'--- git ---'
git rev-parse HEAD origin/main
git log --oneline -1

'--- is the README part of the deploy? ---'
if (Test-Path 'public/README.md') { 'public/README.md exists' } else { 'public/README.md absent (not deployed)' }
Get-ChildItem public -File | Select-Object -ExpandProperty Name

'--- what the site says for /README.md ---'
& curl.exe -s -o NUL -w 'status %{http_code} type %{content_type}' --max-time 12 https://browser.bpiersing.workers.dev/README.md
''
