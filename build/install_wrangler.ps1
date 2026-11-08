$ErrorActionPreference = 'Stop'
Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
$node = Join-Path (Get-Location) 'tools\node'
$npm = Join-Path $node 'npm.cmd'
$tool = Join-Path (Get-Location) 'build\wrangler-tool'
New-Item -ItemType Directory -Force -Path $tool | Out-Null
Set-Location $tool
if (-not (Test-Path 'package.json')) {
    '{ "name": "wrangler-tool", "private": true }' | Set-Content -Encoding utf8 'package.json'
}
$env:Path = "$node;$env:Path"
& $npm install wrangler --no-audit --no-fund --loglevel=error 2>&1 | Select-Object -Last 5
"npm exit: $LASTEXITCODE"
$cli = Join-Path $tool 'node_modules\wrangler\bin\wrangler.js'
"cli present: $(Test-Path $cli)"
if (Test-Path $cli) { & (Join-Path $node 'node.exe') $cli --version }
