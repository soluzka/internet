Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

'python processes before:'
Get-Process python -ErrorAction SilentlyContinue | ForEach-Object { "  $($_.Id)  $([math]::Round($_.WorkingSet64 / 1MB)) MB" }

Start-Process 'songsvc://start'
Start-Sleep -Seconds 10

'python processes after songsvc://start:'
Get-Process python -ErrorAction SilentlyContinue | ForEach-Object { "  $($_.Id)  $([math]::Round($_.WorkingSet64 / 1MB)) MB" }

'--- launcher log tail ---'
Get-Content 'build\launcher_trace.txt' -ErrorAction SilentlyContinue
