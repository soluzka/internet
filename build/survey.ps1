Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

'--- build contents ---'
Get-ChildItem build -Force | Select-Object Mode, Length, LastWriteTime, Name | Sort-Object Name | Format-Table -AutoSize | Out-String

'--- size by top-level item ---'
Get-ChildItem build -Force | ForEach-Object {
    $item = $_
    $bytes = if ($item.PSIsContainer) {
        (Get-ChildItem $item.FullName -Recurse -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
    } else { $item.Length }
    [pscustomobject]@{ Name = $item.Name; MB = [math]::Round($bytes / 1MB, 2) }
} | Sort-Object MB -Descending | Format-Table -AutoSize | Out-String

'--- ignored/untracked check ---'
git status --porcelain --ignored build | Select-Object -First 5
