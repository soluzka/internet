Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

$tracked = @(git ls-files build)
"tracked in build: $($tracked.Count) files"

'--- still ignored (the generated ones) ---'
foreach ($f in @('build/ai_engine', 'build/wrangler-tool', 'build/build.log', 'build/voice_test.wav', 'build/served_index.html', 'build/commit_msg14.txt', 'build/launcher_trace.txt', 'build/diag_health.ps1')) {
    git check-ignore -q $f
    if ($LASTEXITCODE -eq 0) { "$f -> ignored" } else { "$f -> tracked" }
}

''
'--- working tree ---'
git status --short | Out-String
'--- refs ---'
git rev-parse HEAD origin/main
