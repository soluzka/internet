Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
'--- downloader on 8080? ---'
(netstat -ano | findstr ':8080') -join "`n"
'--- cloudflared? ---'
$c = Get-Command cloudflared -ErrorAction SilentlyContinue
if ($c) { $c.Source } else { 'cloudflared not on PATH' }
Get-ChildItem -Path . -Filter 'cloudflared*' -Recurse -Depth 2 -ErrorAction SilentlyContinue |
    Select-Object -First 3 FullName | Format-Table -AutoSize | Out-String
'--- render blueprint ---'
if (Test-Path render.yaml) { Get-Content render.yaml } else { 'no render.yaml' }
