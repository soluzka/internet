$ErrorActionPreference = 'Continue'
Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

& 'song_service\.venv\Scripts\python.exe' -m py_compile 'song_service\app.py' 'app.py'
if ($LASTEXITCODE -eq 0) {
    'compiled ok'
} else {
    "compile failed: $LASTEXITCODE"
}
