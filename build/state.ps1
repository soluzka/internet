Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
Get-Date
'--- listeners ---'
netstat -ano | findstr ':8090 :5001'
'--- python ---'
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Select-Object ProcessId, CreationDate, CommandLine |
    Format-List | Out-String
'--- exe ---'
Get-Process ai_engine -ErrorAction SilentlyContinue |
    Select-Object Id, StartTime | Format-Table -AutoSize | Out-String
