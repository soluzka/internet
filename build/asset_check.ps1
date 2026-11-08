# What the deploy actually uploads, and what the site answers for each file.
# A 200 is not enough: a missing asset falls back to index.html, which is also
# 200, so the content type is what tells an image from the page.
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$site = 'https://browser.bpiersing.workers.dev'

'--- uploaded assets ---'
Get-ChildItem public -File | Select-Object -ExpandProperty Name

''
'--- what the site answers ---'
foreach ($name in (Get-ChildItem public -File | Select-Object -ExpandProperty Name)) {
    $result = & curl.exe -s -o NUL -w '%{http_code} %{content_type}' --max-time 10 "$site/$name"
    "$name -> $result"
}
