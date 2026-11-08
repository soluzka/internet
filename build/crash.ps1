$ErrorActionPreference = 'Continue'
Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

$since = (Get-Date).AddHours(-2)

'=== Application errors / WER ==='
Get-WinEvent -FilterHashtable @{LogName='Application'; StartTime=$since} -ErrorAction SilentlyContinue |
    Where-Object { $_.Message -match 'ai_engine|python|pythonw' } |
    Select-Object TimeCreated, Id, ProviderName,
        @{n='Message';e={ ($_.Message -split "`n")[0..3] -join ' / ' }} |
    Format-List | Out-String
