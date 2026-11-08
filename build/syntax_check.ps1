Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
$html = Get-Content 'public/index.html' -Raw
$pattern = '(?s)<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>'
$blocks = [regex]::Matches($html, $pattern)
"inline script blocks: $($blocks.Count)"
$code = ($blocks | ForEach-Object { $_.Groups[1].Value }) -join "`n;\n"
Set-Content -Path 'build/inline.js' -Value $code -Encoding utf8
& tools/node/node.exe --check build/inline.js
"node --check exit: $LASTEXITCODE"
