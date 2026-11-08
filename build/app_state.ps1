Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
Get-Process ai_engine -ErrorAction SilentlyContinue |
    Select-Object Id, StartTime | Format-Table -AutoSize | Out-String
$code = & curl.exe -s -o NUL -w '%{http_code}' --max-time 4 http://127.0.0.1:5001/api/stats
"api/stats: $code"
if ($code -eq '200') {
    # The user asked for it not to be running: stop what this run started.
    Get-Process ai_engine -ErrorAction SilentlyContinue | ForEach-Object {
        "stopping ai_engine pid $($_.Id)"
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
    $after = & curl.exe -s -o NUL -w '%{http_code}' --max-time 4 http://127.0.0.1:5001/api/stats
    "api/stats now: $after"
}
