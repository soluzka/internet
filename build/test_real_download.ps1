Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

$payload = Join-Path (Get-Location) 'build\dl_request.json'
'{"url":"https://www.youtube.com/watch?v=jNQXAC9IVRw"}' | Set-Content -Path $payload -Encoding ascii -NoNewline

$post = & curl.exe -s -X POST 'http://127.0.0.1:8080/api/download' `
    -H 'Content-Type: application/json' -H 'Origin: https://browser.bpiersing.workers.dev' `
    --data-binary "@$payload" --max-time 30
"POST: $post"

$state = $post | ConvertFrom-Json
$token = $state.token
if (-not $token) { 'no token, stopping'; exit 1 }

for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 3
    $job = & curl.exe -s --max-time 10 "http://127.0.0.1:8080/api/download/$token"
    $jobState = $job | ConvertFrom-Json
    "{0,3}s  status={1}  {2}%" -f (($i + 1) * 3), $jobState.status, $jobState.percent
    if ($jobState.status -eq 'complete' -or $jobState.status -eq 'error') {
        "final: $job"
        break
    }
}
