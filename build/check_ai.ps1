# Does the frozen app find and start the local AI that lives outside dist\?
# curl.exe, because PowerShell 5.1's .NET client drops long Flask responses with
# "the underlying connection was closed", which is a client quirk, not a server one.
$ErrorActionPreference = 'Continue'
$root = 'D:\scrape_videos\scrape_videos\scrape\scrape\my_app\scrape'
$work = Join-Path $root 'build'
$exe = Join-Path $root 'dist\ai_engine.exe'

function Service-Up {
    try {
        (Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8090/health' -TimeoutSec 3).StatusCode -eq 200
    } catch { $false }
}

if (Service-Up) {
    'song service is still running from the last test: stopping it for an honest run'
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like '*song_service*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 3
} else { 'song service: down (as expected)' }

$env:PORT = '5099'
$out = Join-Path $work 'exe_ai.out.log'
$err = Join-Path $work 'exe_ai.err.log'
$proc = Start-Process -FilePath $exe -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $out -RedirectStandardError $err

$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 2
    if ($proc.HasExited) { break }
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5099/' -TimeoutSec 5
        if ($response.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
}
if (-not $ready) {
    'the executable never answered on 5099'
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
    exit 1
}
'exe is up: posting to /api/lyrics with no song service running'

$payload = '{"genre":"electronic music","subject":"rain on a steel roof"}'
& curl.exe -s -S -m 420 -X POST -H 'Content-Type: application/json' `
    -d $payload http://127.0.0.1:5099/api/lyrics

'--- exe log: autostart ---'
Get-Content $out, $err -ErrorAction SilentlyContinue |
    Where-Object { $_ -match 'local AI|song_service' } |
    Select-Object -Last 6

'--- service log ---'
Get-Content (Join-Path $root 'song_service\logs\autostart.log') -Tail 6 -ErrorAction SilentlyContinue

if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
"stopped exe pid $($proc.Id)"
'note: the song service it started is left running; stop it with the launcher or Task Manager'
