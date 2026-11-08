Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

'--- launcher trace (tail) ---'
if (Test-Path build/launcher_trace.txt) { Get-Content build/launcher_trace.txt -Tail 20 } else { 'no trace file' }

''
'--- build logs ---'
Get-ChildItem build -Filter '*.log' -ErrorAction SilentlyContinue | Select-Object Name, Length, LastWriteTime | Format-Table -AutoSize | Out-String

''
'--- python / powershell processes ---'
Get-CimInstance Win32_Process -Filter "Name like '%python%'" | ForEach-Object {
    $cmd = $_.CommandLine
    if ($cmd) { if ($cmd.Length -gt 110) { $cmd = $cmd.Substring(0, 110) } }
    "{0}  {1}" -f $_.ProcessId, $cmd
}

''
'--- ports ---'
foreach ($p in 8080, 8090) {
    $t = Test-NetConnection -ComputerName 127.0.0.1 -Port $p -InformationLevel Quiet -WarningAction SilentlyContinue
    "$p listening: $t"
}
