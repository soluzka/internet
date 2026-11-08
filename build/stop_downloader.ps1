$ids = @(10200, 21072)
foreach ($id in $ids) {
    Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 1
& curl.exe -s -o NUL -w '8080: %{http_code}' --max-time 4 http://127.0.0.1:8080/health
''
