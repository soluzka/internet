Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

$tmp = Join-Path $env:TEMP 'live_index.html'
& curl.exe -s --max-time 30 -o $tmp 'https://browser.bpiersing.workers.dev/'

$local = (Get-FileHash public\index.html -Algorithm SHA256).Hash
$live = (Get-FileHash $tmp -Algorithm SHA256).Hash
"local: $((Get-Item public\index.html).Length) bytes  $local"
"live:  $((Get-Item $tmp).Length) bytes  $live"
if ($local -eq $live) { 'IDENTICAL - the site is serving this exact file' } else { 'DIFFERENT' }

'--- markers that must NOT be on the live page ---'
$text = Get-Content $tmp -Raw
foreach ($m in @('autoStartLocalAI', 'wakeLocalAI(true)')) {
    if ($text -like "*$m*") { "still present: $m" } else { "gone: $m" }
}

'--- markers that must be there ---'
foreach ($m in @('onclick="wakeLocalAI()"', "window.location.href = 'songsvc://start'")) {
    if ($text -like "*$m*") { "present: $m" } else { "MISSING: $m" }
}
