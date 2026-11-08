Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
$matches = Select-String -Path 'song_service/logs/autostart.log' `
    -Pattern 'lyric model|released the lyric|api/lyrics|wrote [0-9]+ sections|Model loaded'
$matches | Select-Object -Last 24 | ForEach-Object { $_.Line }
