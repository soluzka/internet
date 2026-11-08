Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
$urls = @(
    'https://arrow-bell-meters-opponents.trycloudflare.com/health',
    'https://learners-rail-secondary-benefit.trycloudflare.com/health',
    'http://127.0.0.1:8080/health',
    'http://127.0.0.1:8090/health'
)
foreach ($u in $urls) {
    $code = & curl.exe -s -o NUL -w "%{http_code}" --max-time 20 $u
    "{0,-70} {1}" -f $u, $code
}
