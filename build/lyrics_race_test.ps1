Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

'--- stopping song service ---'
@(Get-CimInstance Win32_Process -Filter "Name like '%python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*song_service*' }) | ForEach-Object {
    "kill $($_.ProcessId)"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 3

'--- starting it and hammering /api/lyrics through the whole warm-up ---'
Start-Process -FilePath 'powershell' -WindowStyle Hidden -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PWD 'tools\start_services.ps1'), '-Quiet'
) | Out-Null

$codes = @()
$sw = [Diagnostics.Stopwatch]::StartNew()
while ($sw.Elapsed.TotalSeconds -lt 150) {
    $code = & curl.exe -s -o NUL -w '%{http_code}' --max-time 200 -X POST 'http://127.0.0.1:8090/api/lyrics' `
        -H 'Content-Type: application/json' -d '{"genre":"synthwave","seed":11,"avoid":[]}'
    $codes += $code
    "t+$([int]$sw.Elapsed.TotalSeconds)s -> $code"
    if ($code -eq '200') { break }
    Start-Sleep -Seconds 3
}

''
"codes: $($codes -join ', ')"
if ($codes -contains '500') { 'FAIL: a 500 came back' } else { 'PASS: no 500 during the warm import' }

'--- traceback? ---'
$hits = Select-String -Path song_service\logs\service_err.log -Pattern 'Traceback|cannot import name'
if ($hits) { $hits | Select-Object -Last 2 | ForEach-Object { $_.Line.Trim() } } else { 'none' }
