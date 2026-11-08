Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

'--- will be added ---'
git add -A --dry-run build | Out-String

'--- ignored inside build (sample) ---'
git status --porcelain --ignored build | Select-Object -First 8 | Out-String

'--- check a few by name ---'
foreach ($f in @('build/deploy_and_check.ps1', 'build/race_test.ps1', 'build/survey.ps1', 'build/build.log', 'build/voice_test.wav', 'build/wrangler-tool', 'build/ai_engine', 'build/commit_msg14.txt')) {
    $r = git check-ignore -q $f
    if ($LASTEXITCODE -eq 0) { "$f -> ignored" } else { "$f -> TRACKED" }
}
