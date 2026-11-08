Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

'--- netstat ---'
& netstat.exe -ano | Select-String -Pattern ':8090\s|:8080\s|:5001\s' | ForEach-Object { $_.Line.Trim() }

''
'--- song service processes ---'
Get-CimInstance Win32_Process -Filter "Name like '%python%'" | Where-Object { $_.CommandLine -like '*song_service*' } | ForEach-Object {
    $p = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
    "pid {0}  started {1}  cwd-arg {2}" -f $_.ProcessId, $p.StartTime, ($_.CommandLine -replace '\s+', ' ')
}
