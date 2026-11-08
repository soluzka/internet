Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

'--- who owns 8090 ---'
$owners = @()
foreach ($line in (netstat -ano | Select-String ':8090\s' | Select-String 'LISTENING')) {
    $owners += ($line.Line -split '\s+')[-1]
}
$owners = $owners | Select-Object -Unique
$owners

# The venv launcher and the interpreter it spawns are separate pids; both go.
$stale = @(24552, 9292, 12912, 2036) + $owners
foreach ($id in ($stale | Select-Object -Unique)) {
    $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
    if ($proc) {
        "stopping $id ($([math]::Round($proc.WorkingSet64 / 1MB)) MB)"
        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Seconds 4
& curl.exe -s -o NUL -w '8090 after stop: %{http_code}' --max-time 4 http://127.0.0.1:8090/health
''

$py = Join-Path (Get-Location) 'song_service\.venv\Scripts\python.exe'
$env:SONG_PORT = '8090'
Start-Process -FilePath $py -ArgumentList 'app.py' -WorkingDirectory (Join-Path (Get-Location) 'song_service') `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path (Get-Location) 'song_service\logs\service_out.log') `
    -RedirectStandardError (Join-Path (Get-Location) 'song_service\logs\service_err.log') | Out-Null

for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    $code = & curl.exe -s -o NUL -w '%{http_code}' --max-time 4 http://127.0.0.1:8090/health
    if ($code -eq '200') { "health after $((($i + 1) * 2))s"; break }
}
& curl.exe -s --max-time 6 http://127.0.0.1:8090/health
''
