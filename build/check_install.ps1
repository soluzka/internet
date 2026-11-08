# Does the exe really install the AI where nothing exists? Copied to an empty
# folder with no song_service anywhere near it, asked for lyrics, then stopped
# as soon as the install is visibly running (so it never pulls the whole 16 GB).
$ErrorActionPreference = 'Continue'
$root = 'D:\scrape_videos\scrape_videos\scrape\scrape\my_app\scrape'
$alone = Join-Path $env:TEMP 'ai_engine_install_test'

# Nothing may be listening on 8090, or the exe happily uses that service and the
# install path is never reached. Every exe goes first, because a running one warms
# the project's service back up within seconds.
Get-Process ai_engine -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 3
$listener = (Get-NetTCPConnection -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue).OwningProcess
if ($listener) { Stop-Process -Id $listener -Force -ErrorAction SilentlyContinue; "stopped the leftover service $listener" }
Start-Sleep -Seconds 3
try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8090/health' -TimeoutSec 2 | Out-Null; '8090 still answering'; } catch { '8090 is down' }

if (Test-Path $alone) { cmd.exe /c rmdir /s /q "$alone" }
New-Item -ItemType Directory -Force -Path $alone | Out-Null
Copy-Item (Join-Path $root 'dist\ai_engine.exe') (Join-Path $alone 'ai_engine.exe') -Force
"copied the exe to an empty folder: $alone"

$env:PORT = '5093'
$proc = Start-Process -FilePath (Join-Path $alone 'ai_engine.exe') -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $alone 'run.out.log') `
    -RedirectStandardError (Join-Path $alone 'run.err.log')

$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 2
    if ($proc.HasExited) { break }
    try {
        if ((Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5093/' -TimeoutSec 4).StatusCode -eq 200) {
            $ready = $true
            break
        }
    } catch { }
}
if (-not $ready) { 'the exe never answered on 5093'; exit 1 }

'asking for lyrics with nothing installed nearby:'
& curl.exe -s -S -m 90 -X POST -H 'Content-Type: application/json' `
    -d '{"genre":"electronic music","subject":"rain"}' http://127.0.0.1:5093/api/lyrics
''

$service = Join-Path $alone 'song_service'
'unpacked files:'
Get-ChildItem $service -ErrorAction SilentlyContinue | Select-Object Name, Length | Format-Table | Out-String
'venv created: ' + (Test-Path (Join-Path $service '.venv\Scripts\python.exe'))
'install.cmd present: ' + (Test-Path (Join-Path $service 'logs\install.cmd'))
'install log:'
Get-Content (Join-Path $service 'logs\install.log') -Tail 8 -ErrorAction SilentlyContinue

# Stop the installer and the exe, then remove the test folder.
Get-Process ai_engine -ErrorAction SilentlyContinue | Stop-Process -Force
Get-CimInstance Win32_Process -Filter "Name='python.exe' or Name='cmd.exe' or Name='pip.exe'" |
    Where-Object { $_.CommandLine -like "*ai_engine_install_test*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 3
cmd.exe /c rmdir /s /q "$alone"
"cleaned up: $(-not (Test-Path $alone))"
