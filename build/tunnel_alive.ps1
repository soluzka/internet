Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
Get-Process cloudflared -ErrorAction SilentlyContinue |
    Select-Object Id, StartTime, @{n='MB';e={[math]::Round($_.WorkingSet64/1MB)}} |
    Format-Table -AutoSize | Out-String
'--- last 15 tunnel lines ---'
Get-Content 'build/tunnel_err.log' -Tail 15
'--- downloader requests ---'
Get-Content 'build/dl_err.log' -Tail 6
