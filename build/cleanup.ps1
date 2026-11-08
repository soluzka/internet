Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
# The downloader on 8080 was only there to be tunnelled; the page now calls the
# app on 5001 directly, so stop it.
$line = netstat -ano | Select-String ':8080\s' | Select-String 'LISTENING' | Select-Object -First 1
if ($line) {
    $owner = ($line.Line -split '\s+')[-1]
    "stopping downloader pid $owner"
    Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue
} else { 'nothing on 8080' }

# Only the quick tunnels started for this experiment (after 9:30 this morning).
Get-Process cloudflared -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.StartTime -gt (Get-Date '2026-11-08 09:30')) {
        "stopping cloudflared pid $($_.Id)"
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
}
'--- left running ---'
Get-Process cloudflared, python, ai_engine -ErrorAction SilentlyContinue |
    Select-Object Id, ProcessName, StartTime | Format-Table -AutoSize | Out-String
