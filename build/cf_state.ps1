Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
$home_cf = Join-Path $env:USERPROFILE '.cloudflared'
"cloudflared home: $home_cf"
if (Test-Path $home_cf) {
    Get-ChildItem $home_cf | Select-Object Name, Length, LastWriteTime | Format-Table -AutoSize | Out-String
} else { 'no .cloudflared folder (never logged in)' }
'--- tunnel list ---'
& (Resolve-Path 'tools/bin/cloudflared.exe').Path tunnel list 2>&1 | Select-Object -First 10
