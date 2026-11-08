# With no song_service anywhere near it, the exe should unpack its own copy and
# start installing the AI there; this checks that, then cleans up.
$ErrorActionPreference = 'Continue'
$root = 'D:\scrape_videos\scrape_videos\scrape\scrape\my_app\scrape'
$exe = Join-Path $root 'dist\ai_engine.exe'
$alone = Join-Path $env:TEMP 'ai_engine_alone'

if (Test-Path $alone) { cmd.exe /c rmdir /s /q "$alone" }
New-Item -ItemType Directory -Force -Path $alone | Out-Null
Copy-Item $exe (Join-Path $alone 'ai_engine.exe') -Force
"running from empty folder: $alone"

$env:PORT = '5097'
$proc = Start-Process -FilePath (Join-Path $alone 'ai_engine.exe') -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $alone 'run.out.log') `
    -RedirectStandardError (Join-Path $alone 'run.err.log')

$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 2
    if ($proc.HasExited) { break }
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5097/' -TimeoutSec 5
        if ($response.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
}
if (-not $ready) {
    'the exe never answered on 5097'
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
    exit 1
}

'asking for lyrics with no AI installed anywhere:'
& curl.exe -s -S -m 150 -X POST -H 'Content-Type: application/json' `
    -d '{"genre":"electronic music","subject":"rain"}' http://127.0.0.1:5097/api/lyrics
''

'unpacked in the empty folder:'
Get-ChildItem (Join-Path $alone 'song_service') -ErrorAction SilentlyContinue |
    Select-Object Name, Length | Format-Table | Out-String

'install log (if it started):'
Get-Content (Join-Path $alone 'song_service\logs\install.log') -Tail 5 -ErrorAction SilentlyContinue

'--- exe log ---'
Get-Content (Join-Path $alone 'run.out.log'), (Join-Path $alone 'run.err.log') -ErrorAction SilentlyContinue |
    Where-Object { $_ -match 'song service|AI|install' } |
    Select-Object -Last 5

# Stop everything this test started before deleting the folder.
if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
Get-CimInstance Win32_Process -Filter "Name='python.exe' or Name='cmd.exe'" |
    Where-Object { $_.CommandLine -like "*$alone*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 3
cmd.exe /c rmdir /s /q "$alone"
"cleaned up: $(-not (Test-Path $alone))"
