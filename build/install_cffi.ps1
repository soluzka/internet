Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
$py = (Resolve-Path 'downloader_service/.venv/Scripts/python.exe').Path
& $py -m pip install -q --disable-pip-version-check curl_cffi 2>&1 | Select-Object -Last 3
"pip exit: $LASTEXITCODE"
& $py -c "import curl_cffi, yt_dlp; print('curl_cffi', curl_cffi.__version__); print('yt-dlp', yt_dlp.version.__version__)"

# Restart the service so the new option is in effect.
$line = netstat -ano | Select-String ':8080\s' | Select-String 'LISTENING' | Select-Object -First 1
if ($line) {
    $owner = ($line.Line -split '\s+')[-1]
    "stopping downloader pid $owner"
    Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}
& powershell -NoProfile -ExecutionPolicy Bypass -File tools/start_downloader.ps1 -Hidden
'--- health ---'
& curl.exe -s --max-time 8 http://127.0.0.1:8080/health
''
