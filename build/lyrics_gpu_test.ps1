Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
$body = '{"genre":"techno","subject":"bass night city rain","seed":7}'
$body | Set-Content 'build\lyrics_request.json' -Encoding ascii -NoNewline

$sw = [System.Diagnostics.Stopwatch]::StartNew()
$out = & curl.exe -s -X POST 'http://127.0.0.1:8090/api/lyrics' -H 'Content-Type: application/json' --data-binary '@build/lyrics_request.json' --max-time 400
$sw.Stop()
"seconds: $([math]::Round($sw.Elapsed.TotalSeconds, 1))"
$out | Set-Content 'build\lyrics_result.json' -Encoding utf8
$parsed = $out | ConvertFrom-Json
"sections: $($parsed.sections.Count)"
$parsed.sections | ForEach-Object { "  [$($_.section)] $($_.lines.Count) lines: $($_.lines[0])" }
'--- gpu ---'
nvidia-smi --query-gpu=memory.used --format=csv,noheader
'--- service log tail ---'
Get-Content 'song_service\logs\service_err.log' -Tail 6 -ErrorAction SilentlyContinue
