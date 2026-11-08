# Does this machine come back on its own after a restart?
# Checks the three links in the chain and the state at the end of it: the Startup
# entry, the songsvc:// target the site's button uses, and whether both services
# are answering now.
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$startup = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup\AI song services.cmd'
'--- startup entry ---'
if (Test-Path $startup) {
    "present: $startup"
    Get-Content $startup
} else {
    "MISSING: $startup  (run tools\install_autostart.ps1)"
}

''
'--- songsvc protocol target ---'
$target = (Get-ItemProperty -Path 'HKCU:\Software\Classes\songsvc\shell\open\command' -ErrorAction SilentlyContinue).'(default)'
if ($target) { $target } else { 'not registered (run tools\start_services.ps1)' }

''
'--- services now ---'
foreach ($p in 8080, 8090) {
    $code = & curl.exe -s -o NUL -w '%{http_code}' --max-time 3 "http://127.0.0.1:$p/health"
    "$p -> $code"
}

''
'--- song health ---'
& curl.exe -s --max-time 5 http://127.0.0.1:8090/health
''

'--- song service processes ---'
@(Get-CimInstance Win32_Process -Filter "Name like '%python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*song_service*' } |
    ForEach-Object { $_.ProcessId }) -join ', '

''
'--- git ---'
git status --short | Out-String
