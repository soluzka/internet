$ErrorActionPreference = 'Continue'
Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

$log = 'song_service/logs/autostart.log'

'=== song + status lines ==='
Select-String -Path $log -Pattern 'POST /api/song','" 4[0-9][0-9] ','" 5[0-9][0-9] ','Traceback','Exception','status' |
    Select-Object -Last 40 |
    ForEach-Object { $_.Line }

'=== last 15 lines ==='
Get-Content $log -Tail 15

'=== port 8090 / 5001 listeners ==='
netstat -ano | Select-String ':8090',':5001'

'=== python / exe processes ==='
Get-Process | Where-Object { $_.ProcessName -match 'python|ai_engine' } |
    Select-Object Id, ProcessName, StartTime, WS |
    Format-Table -AutoSize | Out-String
