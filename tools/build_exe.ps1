# Freeze the desktop app, then prove the result runs.
#
#   powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1
#
# Needs the project venv (root requirements.txt: pyinstaller,
# pyinstaller-hooks-contrib) and ai_engine.spec. A build that only produces a
# file is not a build: the smoke test at the end starts the executable on a
# spare port and asks it for the page.

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$spec = Join-Path $root 'ai_engine.spec'
if (-not (Test-Path $spec)) {
    Write-Host 'ai_engine.spec is missing from this checkout.'
    Write-Host 'It was deleted in 1994807; restore it and run this again:'
    Write-Host '  git checkout c0f53ab -- ai_engine.spec'
    exit 1
}

$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Host "No virtual environment at $python"
    Write-Host '  python -m venv .venv'
    Write-Host '  .venv\Scripts\python -m pip install -r requirements.txt'
    exit 1
}

$log = Join-Path $root 'build_exe.log'
& $python -m PyInstaller --clean --noconfirm ai_engine.spec *> $log
$code = $LASTEXITCODE
"pyinstaller exit code: $code"

if ($code -ne 0) {
    Get-Content $log -Tail 20
    exit $code
}

Get-Content $log -Tail 3
Get-ChildItem (Join-Path $root 'dist') |
    Select-Object Name, Length, LastWriteTime |
    Format-Table | Out-String

# One-file bundles unpack ~180 MB before Flask binds, so this waits, not polls.
$exe = Join-Path $root 'dist\ai_engine.exe'
if (-not (Test-Path $exe)) { exit 0 }

$env:PORT = '5099'
$proc = Start-Process -FilePath $exe -PassThru -WindowStyle Hidden
$answered = $false

for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 2
    if ($proc.HasExited) { break }
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5099/' -TimeoutSec 5
        if ($response.StatusCode -eq 200) { $answered = $true; break }
    } catch {
        # still unpacking
    }
}

if ($answered) {
    'smoke test: the executable served http://127.0.0.1:5099/ with HTTP 200'
} elseif ($proc.HasExited) {
    "smoke test: the executable exited with code $($proc.ExitCode)"
} else {
    'smoke test: no answer on 5099 after 2 minutes'
}

if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
