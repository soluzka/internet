Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

'--- working tree (empty = nothing uncommitted) ---'
git status --short | Out-String

'--- local vs github ---'
git rev-parse HEAD
git ls-remote origin refs/heads/main

'--- last three commits ---'
git log --oneline -3 | Out-String

'--- would anything be lost? (tracked changes vs remote) ---'
git fetch origin --quiet 2>&1 | Out-String
git log --oneline origin/main..HEAD | Out-String

'--- boot time ---'
(Get-CimInstance Win32_OperatingSystem).LastBootUpTime

'--- launcher trace since boot ---'
$boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
Get-Content build\launcher_trace.txt -Tail 30 | Where-Object {
    $_ -match '^\d{4}' -and ([datetime]::ParseExact(($_ -split ' ')[0] + ' ' + ($_ -split ' ')[1], 'yyyy-MM-dd HH:mm:ss', $null) -gt $boot)
}

'--- services now ---'
foreach ($p in 8080, 8090) {
    $code = & curl.exe -s -o NUL -w '%{http_code}' --max-time 4 "http://127.0.0.1:$p/health"
    "$p -> $code"
}
