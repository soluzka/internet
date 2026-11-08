$w = Join-Path $env:USERPROFILE '.wrangler'
if (Test-Path $w) {
    'wrangler config:'
    Get-ChildItem $w -Recurse -Depth 2 -File -ErrorAction SilentlyContinue |
        Select-Object FullName, Length | Format-Table -AutoSize | Out-String
    $tok = Join-Path $w 'config\default.toml'
    if (Test-Path $tok) { 'has oauth token: ' + ((Get-Content $tok) -match 'oauth_token').Count }
} else { 'no ~/.wrangler (never logged in)' }

'--- node.exe candidates ---'
$candidates = @(
    'C:\Program Files\nodejs\node.exe',
    (Join-Path $env:LOCALAPPDATA 'Programs\nodejs\node.exe'),
    (Join-Path $env:APPDATA 'npm\node.exe'),
    'C:\ProgramData\chocolatey\bin\node.exe'
)
foreach ($c in $candidates) { "{0}  {1}" -f (Test-Path $c), $c }
Get-ChildItem (Join-Path $env:APPDATA 'nvm') -ErrorAction SilentlyContinue |
    Select-Object Name -First 5 | Format-Table -AutoSize | Out-String
