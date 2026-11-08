# Regression test: two launcher runs inside the torch-import window must leave
# exactly one song service. Before the process check in tools\start_services.ps1
# the second run started a duplicate that then could not bind 8090.
#
# This stops the song service, so it is a deliberate, visible action: run it when
# no song is rendering.
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function SongPids {
    Get-CimInstance Win32_Process -Filter "Name like '%python%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*song_service*' } |
        ForEach-Object { $_.ProcessId }
}

'stopping the song service'
SongPids | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 4
'pids after stop: ' + ((SongPids) -join ', ')

'--- launcher run 1 ---'
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'tools\start_services.ps1') -NoWarm
'--- launcher run 2 (immediately, inside the startup window) ---'
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'tools\start_services.ps1') -NoWarm

'--- waiting 55s for it to bind ---'
Start-Sleep -Seconds 55
$pids = @(SongPids)
"song service processes: $($pids.Count)  -> $($pids -join ', ')"
& curl.exe -s --max-time 6 http://127.0.0.1:8090/health
''
