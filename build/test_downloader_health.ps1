Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
$py = (Resolve-Path 'downloader_service/.venv/Scripts/python.exe').Path

$jar = @(
    '# Netscape HTTP Cookie File',
    '.youtube.com	TRUE	/	TRUE	0	TEST_COOKIE	1'
) -join "`n"

$env:PORT = '8080'
$env:YT_COOKIES = $jar
Start-Process -FilePath $py -ArgumentList 'app.py' -WorkingDirectory (Resolve-Path 'downloader_service').Path `
    -WindowStyle Hidden -RedirectStandardOutput 'build/dl_out2.log' -RedirectStandardError 'build/dl_err2.log' | Out-Null

for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 700
    $code = & curl.exe -s -o NUL -w '%{http_code}' --max-time 3 http://127.0.0.1:8080/health
    if ($code -eq '200') { break }
}
'--- /health ---'
& curl.exe -s --max-time 8 http://127.0.0.1:8080/health
''
'--- cookie file written ---'
$path = Join-Path $env:TEMP 'yt_cookies.txt'
"exists: $(Test-Path $path)"
if (Test-Path $path) { Get-Content $path | Select-Object -Last 2 }
