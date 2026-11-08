Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

'--- last boot / logon ---'
$os = Get-CimInstance Win32_OperatingSystem
"booted: $($os.LastBootUpTime)"
"now:    $(Get-Date)"

'--- launcher trace (last 15) ---'
if (Test-Path build\launcher_trace.txt) {
    Get-Content build\launcher_trace.txt -Tail 15
} else { 'no trace file' }

'--- song service error log (last 25) ---'
$err = 'song_service\logs\service_err.log'
if (Test-Path $err) {
    "size $([math]::Round((Get-Item $err).Length/1KB,1)) KB, written $((Get-Item $err).LastWriteTime)"
    Get-Content $err -Tail 25
} else { 'no error log' }

'--- log file times ---'
foreach ($p in @('song_service\logs\service_out.log','song_service\logs\service_err.log','build\downloader_err.log','build\downloader_out.log')) {
    if (Test-Path $p) { '{0,-40} {1}' -f $p, (Get-Item $p).LastWriteTime }
}
