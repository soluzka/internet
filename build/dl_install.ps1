Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
$py = 'downloader_service/.venv/Scripts/python.exe'
if (-not (Test-Path $py)) {
    python -m venv downloader_service/.venv
}
& $py -m pip install -q --disable-pip-version-check -r downloader_service/requirements.txt *> build/dl_install.log
"pip exit: $LASTEXITCODE"
& $py -c "import flask, flask_cors, yt_dlp, imageio_ffmpeg; print('deps ok')"
"import exit: $LASTEXITCODE"
Get-Content build/dl_install.log -Tail 4
