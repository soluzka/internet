Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
$exe = Join-Path (Get-Location) 'dist\ai_engine.exe'
"exe: $exe  $([math]::Round((Get-Item $exe).Length/1MB,1)) MB  $((Get-Item $exe).LastWriteTime)"

$existing = netstat -ano | Select-String ':5001\s' | Select-String 'LISTENING'
if ($existing) { 'the app is already listening on 5001' }
else {
    $p = Start-Process -FilePath $exe -WorkingDirectory (Split-Path $exe) -WindowStyle Hidden -PassThru
    "started pid $($p.Id)"
}

for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 2
    $code = & curl.exe -s -o NUL -w '%{http_code}' --max-time 4 http://127.0.0.1:5001/api/stats
    if ($code -eq '200') { "app answers /api/stats after $((($i+1)*2))s"; break }
}
'--- final ---'
& curl.exe -s -o NUL -w 'api/stats: %{http_code}' --max-time 6 http://127.0.0.1:5001/api/stats
''
& curl.exe -s -o NUL -w 'index:     %{http_code}' --max-time 6 http://127.0.0.1:5001/
''
