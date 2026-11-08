# What is actually inside the packaged app: the page, the sample bank, and voice.
$ErrorActionPreference = 'Continue'
$root = 'D:\scrape_videos\scrape_videos\scrape\scrape\my_app\scrape'
$exe = Join-Path $root 'dist\ai_engine.exe'
$work = Join-Path $root 'build'
$wav = Join-Path $work 'voice_test.wav'

if (-not (Test-Path $wav)) {
    Add-Type -AssemblyName System.Speech
    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $synth.SetOutputToWaveFile($wav)
    $synth.Speak('Machines hum beneath the floor and the cold steel holds the water')
    $synth.Dispose()
    "made test audio: $wav"
}

$env:PORT = '5099'
$out = Join-Path $work 'exe_verify.out.log'
$err = Join-Path $work 'exe_verify.err.log'
$proc = Start-Process -FilePath $exe -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $out -RedirectStandardError $err

$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 2
    if ($proc.HasExited) { break }
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5099/' -TimeoutSec 5
        if ($response.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
}
if (-not $ready) {
    'the exe never answered on 5099'
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
    exit 1
}

$page = Join-Path $work 'served_index.html'
& curl.exe -s -o $page -w 'page: HTTP %{http_code}, %{size_download} bytes' http://127.0.0.1:5099/
''

$sample = Join-Path $work 'served_sample.mp3'
& curl.exe -s -o $sample -w 'sample: HTTP %{http_code}, %{size_download} bytes' `
    http://127.0.0.1:5099/samples/acoustic_grand_piano-C3.mp3
''

'voice: posting speech to /api/transcribe'
& curl.exe -s -S -m 300 -X POST -H 'Content-Type: audio/wav' `
    --data-binary "@$wav" http://127.0.0.1:5099/api/transcribe
''

'--- whisper lines from the exe log ---'
Get-Content $out, $err -ErrorAction SilentlyContinue |
    Where-Object { $_ -match 'Whisper|VAD|transcrib' } |
    Select-Object -Last 5

if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
"stopped exe pid $($proc.Id)"
