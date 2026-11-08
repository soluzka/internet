$ErrorActionPreference = 'Continue'
Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

'=== timeline 04:00-04:44, API lines + model lines, no progress bars ==='
Get-Content song_service/logs/autostart.log | Where-Object {
    $_ -match '\[08/Nov/2026 04:(0|1|2|3|4)' -and ($_ -match 'POST|GET /api/song/|wrote|Model loaded|diffusion|prompt|lyrics|Starting|Warming|Unpacked|Traceback')
} | Select-Object -Last 60
