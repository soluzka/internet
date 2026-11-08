Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

$cmdPath = 'HKCU:\Software\Classes\songsvc\shell\open\command'

'--- pointing it at a stale path, as if the folder had moved ---'
Set-ItemProperty -Path $cmdPath -Name '(default)' -Value 'powershell -File "D:\old\place\start_services.ps1"'
(Get-ItemProperty -Path $cmdPath).'(default)'

'--- run the launcher, as Startup or the site would ---'
& (Join-Path (Get-Location) 'tools\start_services.ps1') -Quiet
Start-Sleep -Seconds 2

'--- what the registry says now ---'
(Get-ItemProperty -Path $cmdPath).'(default)'
