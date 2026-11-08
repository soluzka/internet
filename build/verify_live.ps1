# Is the deployed site the one built from this folder, and is the repo clean?
# Checks for the strings that only exist in the newer page, then the git state.
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$site = 'https://browser.bpiersing.workers.dev'

$page = & curl.exe -s --max-time 15 "$site/"
foreach ($needle in @('wakeBtn', 'wakeLocalAI', 'gpuChip', 'refreshGpu', 'songsvc://start')) {
    if ($page -match [regex]::Escape($needle)) { "live page: $needle  yes" } else { "live page: $needle  MISSING" }
}

'--- git ---'
git status --short | Out-String
git rev-parse HEAD origin/main
git log --oneline -3 | Out-String
