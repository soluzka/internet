Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
$m = Select-String -Path 'build/tunnel2_err.log' -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -AllMatches
$url = $null
foreach ($l in $m) { foreach ($x in $l.Matches) { if (-not $url) { $url = $x.Value } } }
"tunnel url: $url"
if ($url) {
    & curl.exe -s -o NUL -w "public health: %{http_code}`n" --max-time 25 "$url/health"
    & curl.exe -s -o NUL -w "public root:   %{http_code}`n" --max-time 25 "$url/"
}
