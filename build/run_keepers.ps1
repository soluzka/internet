Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'

'===== asset_check ====='
& powershell -NoProfile -ExecutionPolicy Bypass -File build/asset_check.ps1

'===== service_state ====='
& powershell -NoProfile -ExecutionPolicy Bypass -File build/service_state.ps1

'===== autostart_status ====='
& powershell -NoProfile -ExecutionPolicy Bypass -File build/autostart_status.ps1
