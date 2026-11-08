Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
Get-Content song_service\logs\service_err.log -Tail 12 -ErrorAction SilentlyContinue
'--- health ---'
& curl.exe -s --max-time 6 http://127.0.0.1:8090/health
''
'--- memory now ---'
Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    '{0}  {1} MB' -f $_.Id, [math]::Round($_.WorkingSet64 / 1MB)
}
