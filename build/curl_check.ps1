Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
$local = & curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:8080/health
"local: $local"
$pub = & curl.exe -s -i --max-time 25 https://purpose-miles-isolation-duncan.trycloudflare.com/health
$pub | Select-Object -First 12
'--- memory ---'
$os = Get-CimInstance Win32_OperatingSystem
"free GB: $([math]::Round($os.FreePhysicalMemory/1MB,2)) / total GB: $([math]::Round($os.TotalVisibleMemorySize/1MB,2))"
