$ErrorActionPreference = 'Continue'
Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

'=== 4:42 onward, no progress bars ==='
Get-Content song_service/logs/autostart.log |
    Where-Object { $_ -notmatch '%\|' -and $_ -ne '' } |
    Select-String -Pattern '\[08/Nov/2026 04:4' |
    Select-Object -Last 45 |
    ForEach-Object { $_.Line }

'=== wrote / error / traceback ==='
Select-String -Path song_service/logs/autostart.log -Pattern 'wrote|Traceback|Error|Exception' |
    Select-Object -Last 12 |
    ForEach-Object { $_.Line }

'=== last_song.wav ==='
Get-ChildItem song_service/logs/last_song.wav | Select-Object Length,LastWriteTime | Format-List | Out-String

'=== root logs dir ==='
Get-ChildItem logs -ErrorAction SilentlyContinue | Select-Object Name,Length,LastWriteTime | Format-Table -AutoSize | Out-String
