Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
Select-String -Path 'build/tunnel_err.log' -Pattern 'trycloudflare|Registered tunnel|ERR' -Context 0,0 |
    Select-Object -Last 12 | ForEach-Object { $_.Line }
'--- retry health ---'
$u = 'https://purpose-miles-isolation-duncan.trycloudflare.com/health'
for ($i = 0; $i -lt 3; $i++) {
    try {
        $r = Invoke-WebRequest -Uri $u -TimeoutSec 20 -UseBasicParsing
        "status $($r.StatusCode): $($r.Content)"
        break
    } catch {
        "try $i : $($_.Exception.Message)"
        Start-Sleep -Seconds 3
    }
}
