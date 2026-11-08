Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

'--- dry run ---'
$added = git add -A --dry-run build
"would add: $($added.Count) files"

'--- total size of those files ---'
$sum = 0
$big = @()
foreach ($line in $added) {
    $path = ($line -replace "^add '", '' -replace "'$", '')
    if (Test-Path $path) {
        $len = (Get-Item $path).Length
        $sum += $len
        if ($len -gt 1MB) { $big += ('{0} MB  {1}' -f [math]::Round($len/1MB,1), $path) }
    }
}
"total MB: $([math]::Round($sum/1MB,2))"
if ($big.Count) { '--- over 1 MB ---'; $big } else { 'nothing over 1 MB' }

'--- non-.ps1 files being added ---'
$added | Where-Object { $_ -notmatch '\.ps1' }
