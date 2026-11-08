# Deploy the Worker and confirm the new version actually holds what was built.
# The deploy line is quoted from the portable Node in tools/node; there is no
# system Node on this machine and no Cloudflare credentials are needed here.
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$site = 'https://browser.bpiersing.workers.dev'

& tools/node/node.exe build/wrangler-tool/node_modules/wrangler/bin/wrangler.js deploy 2>&1 |
    Select-Object -Last 2 | Out-String

$page = & curl.exe -s --max-time 15 "$site/"
if ($page -match 'wakeBtn') { 'deployed page has the header button' } else { 'NOT FOUND: wakeBtn' }
if ($page -match 'wakeLocalAI') { 'deployed page has the wake function' } else { 'NOT FOUND: wakeLocalAI' }
