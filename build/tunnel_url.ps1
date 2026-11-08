Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
$lines = Select-String -Path 'build/tunnel_err.log' -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -AllMatches
$url = $null
foreach ($l in $lines) { foreach ($m in $l.Matches) { if (-not $url) { $url = $m.Value } } }
"tunnel url: $url"
if ($url) {
    try { (Invoke-RestMethod -Uri "$url/health" -TimeoutSec 25) | ConvertTo-Json }
    catch { "public health failed: $($_.Exception.Message)" }
}
