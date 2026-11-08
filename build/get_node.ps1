$ErrorActionPreference = 'Stop'
Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

$dest = Join-Path (Get-Location) 'tools\node'
$nodeExe = Join-Path $dest 'node.exe'
if (Test-Path $nodeExe) { "already there: $nodeExe"; & $nodeExe --version; exit 0 }

$ProgressPreference = 'SilentlyContinue'
$index = Invoke-RestMethod 'https://nodejs.org/dist/index.json' -TimeoutSec 60
$lts = $index | Where-Object { $_.lts } | Select-Object -First 1
$version = $lts.version
$zipName = "node-$version-win-x64.zip"
$url = "https://nodejs.org/dist/$version/$zipName"
"downloading $url"

$zip = Join-Path (Get-Location) 'build\node.zip'
Invoke-WebRequest -Uri $url -OutFile $zip -TimeoutSec 600
"downloaded $([math]::Round((Get-Item $zip).Length/1MB,1)) MB"

$extract = Join-Path (Get-Location) 'build\node_extract'
Remove-Item $extract -Recurse -Force -ErrorAction SilentlyContinue
Expand-Archive -Path $zip -DestinationPath $extract -Force
$inner = Get-ChildItem $extract -Directory | Select-Object -First 1
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item (Join-Path $inner.FullName '*') $dest -Recurse -Force
Remove-Item $extract -Recurse -Force
Remove-Item $zip -Force

"node: $(& $nodeExe --version)"
"npm:  $(& (Join-Path $dest 'npm.cmd') --version)"
