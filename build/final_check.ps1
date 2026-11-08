Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

'--- tracked in build ---'
git ls-files build

''
'--- untracked (should be none) ---'
git status --short | Out-String

''
'--- refs ---'
git rev-parse HEAD origin/main
