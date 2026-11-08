Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

# The quick tunnel started earlier registers but the edge answers 404, so replace
# it and force HTTP/2, which works on networks that mangle QUIC.
Get-Process cloudflared -ErrorAction SilentlyContinue |
    Where-Object { $_.StartTime -gt (Get-Date).AddMinutes(-20) } |
    ForEach-Object { Stop-Process -Id $_.Id -Force }
Start-Sleep -Seconds 2

Remove-Item 'build/tunnel2_err.log' -ErrorAction SilentlyContinue
$cf = Start-Process -FilePath (Resolve-Path 'tools/bin/cloudflared.exe').Path `
    -ArgumentList 'tunnel','--url','http://127.0.0.1:8080','--protocol','http2','--no-autoupdate' `
    -WindowStyle Hidden -RedirectStandardOutput 'build/tunnel2_out.log' -RedirectStandardError 'build/tunnel2_err.log' -PassThru
"cloudflared pid: $($cf.Id)"

$url = $null
for ($i = 0; $i -lt 25; $i++) {
    Start-Sleep -Seconds 2
    $m = Select-String -Path 'build/tunnel2_err.log' -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -ErrorAction SilentlyContinue
    if ($m) { $url = ($m | Select-Object -First 1).Matches[0].Value; break }
}
"tunnel url: $url"
if ($url) {
    Start-Sleep -Seconds 3
    & curl.exe -s -o NUL -w "public health: %{http_code}`n" --max-time 25 "$url/health"
    '--- origin saw ---'
    Get-Content 'build/dl_err.log' -Tail 3
}
