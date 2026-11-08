Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
& powershell -NoProfile -ExecutionPolicy Bypass -File 'tools\build_exe.ps1' *> 'build\build.log'
"build finished with exit code $LASTEXITCODE"
