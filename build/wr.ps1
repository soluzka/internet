param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
& tools\node\node.exe build\wrangler-tool\node_modules\wrangler\bin\wrangler.js @Args
exit $LASTEXITCODE
