Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
$env:PORT = '8080'
$py = (Resolve-Path 'downloader_service/.venv/Scripts/python.exe').Path

$dl = Start-Process -FilePath $py -ArgumentList 'app.py' -WorkingDirectory (Resolve-Path 'downloader_service').Path `
    -WindowStyle Hidden -RedirectStandardOutput 'build/dl_out.log' -RedirectStandardError 'build/dl_err.log' -PassThru
"downloader pid: $($dl.Id)"

Start-Sleep -Seconds 4
'--- local health ---'
try { (Invoke-RestMethod -Uri 'http://127.0.0.1:8080/health' -TimeoutSec 6) | ConvertTo-Json } catch { 'local health failed' }

if (-not (Test-Path 'build/tunnel_err.log')) { New-Item -ItemType File 'build/tunnel_err.log' | Out-Null }
$cf = Start-Process -FilePath (Resolve-Path 'tools/bin/cloudflared.exe').Path `
    -ArgumentList 'tunnel','--url','http://127.0.0.1:8080','--no-autoupdate' `
    -WindowStyle Hidden -RedirectStandardOutput 'build/tunnel_out.log' -RedirectStandardError 'build/tunnel_err.log' -PassThru
"cloudflared pid: $($cf.Id)"

$url = $null
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    $hit = Select-String -Path 'build/tunnel_err.log' -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($hit) { $url = $hit.Matches[0].Value; break }
}
"tunnel url: $url"
if ($url) {
    '--- public health ---'
    try {
        (Invoke-RestMethod -Uri "$url/health" -TimeoutSec 20) | ConvertTo-Json
    } catch { "public health failed: $($_.Exception.Message)" }
}
