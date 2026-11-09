Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

'--- stop song service ---'
@(Get-CimInstance Win32_Process -Filter "Name like '%python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*song_service*' }) | ForEach-Object {
    "kill $($_.ProcessId)"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 3

'--- start with SONG_WARM=1 via the launcher ---'
& powershell -NoProfile -ExecutionPolicy Bypass -File tools/start_services.ps1 -Quiet

'--- poll health until the model is loaded (max 4 min) ---'
$sw = [Diagnostics.Stopwatch]::StartNew()
$last = ''
while ($sw.Elapsed.TotalSeconds -lt 240) {
    $raw = & curl.exe -s --max-time 10 'http://127.0.0.1:8090/health'
    if ($raw) {
        try {
            $h = $raw | ConvertFrom-Json
            $line = "t+{0,3}s  loaded={1}  lyrics_loaded={2}" -f [int]$sw.Elapsed.TotalSeconds, $h.loaded, $h.lyrics_loaded
            if ($line -ne $last) { $line; $last = $line }
            if ($h.loaded -and $h.lyrics_loaded) { break }
        } catch { }
    }
    Start-Sleep -Seconds 5
}

''
'--- what the service said ---'
Get-Content song_service\logs\service_out.log -Tail 12

''
'--- did the warm-up fail? ---'
$fail = Select-String -Path song_service\logs\service_out.log -Pattern 'warm load failed'
if ($fail) { $fail | ForEach-Object { $_.Line } } else { 'no warm load failure' }
