# The local services the site depends on, and what they say about themselves.
# /health on 8090 names the device, so this answers "is it on the GPU" without
# opening a console or guessing from nvidia-smi (the weights page in, so idle
# VRAM looks like nothing is loaded even when it is).
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

'--- song service (8090) ---'
$song = & curl.exe -s --max-time 6 http://127.0.0.1:8090/health
if ($song) { $song } else { 'no answer' }

'--- downloader (8080) ---'
& curl.exe -s -o NUL -w '%{http_code}' --max-time 4 http://127.0.0.1:8080/health
''

'--- python processes ---'
Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    '{0}  {1} MB  started {2}' -f $_.Id, [math]::Round($_.WorkingSet64 / 1MB), $_.StartTime
}
