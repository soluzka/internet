# Freeze the desktop app, then prove the result runs.
#
#   powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1
#
# The build lives here, not in a .spec file, so every file the app needs at
# runtime is declared in one readable command. PyInstaller only follows imports:
# it does not know that faster_whisper reads assets\silero_vad_v6.onnx off disk,
# which is why a build without --collect-all produced an EXE whose voice search
# crashed into "NoSuchFile: silero_vad_v6.onnx" and fell back to the Windows
# recogniser. --collect-all packages a library's data, binaries and submodules
# together, which is what these entries are for.

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Host "No virtual environment at $python"
    Write-Host '  python -m venv .venv'
    Write-Host '  .venv\Scripts\python -m pip install -r requirements.txt'
    exit 1
}

$arguments = @(
    '-m', 'PyInstaller',
    '--noconfirm', '--clean', '--onefile', '--console',
    '--name', 'ai_engine',
    # Keep the regenerated spec inside the ignored build folder instead of the
    # repo root, where it would look like a file someone deleted on purpose.
    '--specpath', 'build',
    # Static site and icon, unpacked to the bundle root the way app.py expects.
    # Absolute, because --specpath makes PyInstaller resolve data paths against
    # the generated spec in build\ rather than against the repo root.
    '--add-data', "$(Join-Path $root 'public');public",
    '--add-data', "$(Join-Path $root 'cinema.ico');.",
    # The committed index snapshot, so a fresh machine is not an empty library.
    '--add-data', "$(Join-Path $root 'data\video_index.db');data",
    # The service's source (~120 KB, not its 16 GB of packages and weights), so
    # the exe can create song_service wherever it is and install the AI there.
    '--add-data', "$(Join-Path $root 'song_service\app.py');song_service",
    '--add-data', "$(Join-Path $root 'song_service\lyrics.py');song_service",
    '--add-data', "$(Join-Path $root 'song_service\install.py');song_service",
    '--add-data', "$(Join-Path $root 'song_service\models.json');song_service",
    # The socket stack the page speaks to.
    '--collect-all', 'flask_socketio',
    '--collect-all', 'engineio',
    # Voice search: the VAD onnx asset, the CTranslate2 runtime and its DLLs,
    # PyAV for decoding, and the ffmpeg binary so the machine needs none on PATH.
    '--collect-all', 'faster_whisper',
    '--collect-all', 'ctranslate2',
    '--collect-all', 'onnxruntime',
    '--collect-all', 'av',
    '--collect-all', 'imageio_ffmpeg',
    # Downloads: yt-dlp loads extractors lazily by module name, and curl_cffi
    # carries its own libcurl, so neither is safe to leave to import analysis.
    '--collect-all', 'yt_dlp',
    '--collect-all', 'curl_cffi',
    '--copy-metadata', 'yt_dlp',
    '--copy-metadata', 'faster_whisper',
    'app.py'
)

# Whisper reads its weights from a folder, not an import. Ship the copy already
# in the Hugging Face cache so voice search works with no network on first run.
$snapshots = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.cache\huggingface\hub\models--Systran--faster-whisper-base.en\snapshots'
$weights = Get-ChildItem $snapshots -Directory -ErrorAction SilentlyContinue |
    Where-Object { Test-Path (Join-Path $_.FullName 'model.bin') } |
    Select-Object -First 1

if ($weights) {
    "bundling whisper weights: $($weights.FullName)"
    $arguments = $arguments[0..($arguments.Count - 2)] + @(
        '--add-data', "$($weights.FullName);whisper/base.en", 'app.py')
} else {
    'no cached whisper weights found: voice search will download them on first use'
}

$log = Join-Path $root 'build_exe.log'
& $python @arguments *> $log
$code = $LASTEXITCODE
"pyinstaller exit code: $code"

if ($code -ne 0) {
    Get-Content $log -Tail 20
    exit $code
}

Get-Content $log -Tail 3

# Where the AI lives, reported and never touched. This script builds; it does
# not install or download the model. The exe loads the AI from song_service
# beside itself, or one level up -- this layout:
#
#     <project>\dist\ai_engine.exe   +   <project>\song_service\
#
# and installs anything missing there itself, on first use.
$service = Join-Path $root 'song_service'
$aiPython = Join-Path $service '.venv\Scripts\python.exe'
$aiModels = Join-Path $service 'models'
if ((Test-Path $aiPython) -and (Test-Path $aiModels)) {
    "AI found in ${service}: the exe loads it from there"
} elseif (Test-Path (Join-Path $service 'app.py')) {
    "AI in $service looks incomplete: the exe installs what is missing on first use"
} else {
    'warning: no song_service folder, so the exe has no AI to load'
}

Get-ChildItem (Join-Path $root 'dist') |
    Select-Object Name, Length, LastWriteTime |
    Format-Table | Out-String

# One-file bundles unpack the whole thing before Flask binds, so this waits.
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
