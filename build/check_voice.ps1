# Voice search in the frozen app: synthesise a known sentence, post it to the
# EXE's /api/transcribe, and show the transcript it returns.
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$work = Join-Path $root 'build'
$exe = Join-Path $root 'dist\ai_engine.exe'
$wav = Join-Path $work 'voice_test.wav'

Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SetOutputToWaveFile($wav)
$synth.Rate = 0
$synth.Speak('Machines hum beneath the floor and the cold steel holds the water')
$synth.Dispose()
"spoke test sentence into: $wav ({0:N0} KB)" -f ((Get-Item $wav).Length / 1KB)

$env:PORT = '5099'
$out = Join-Path $work 'exe_voice.out.log'
$err = Join-Path $work 'exe_voice.err.log'
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
    'the executable never answered on 5099'
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
    exit 1
}
'executable is up, posting audio to /api/transcribe (Whisper load takes a moment)'

try {
    $answer = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5099/api/transcribe' `
        -Method Post -InFile $wav -ContentType 'audio/wav' -TimeoutSec 240
    "HTTP $($answer.StatusCode)"
    $answer.Content
} catch {
    "transcribe call failed: $($_.Exception.Message)"
}

Start-Sleep -Seconds 1
'--- whisper lines from the exe log ---'
Get-Content $out, $err -ErrorAction SilentlyContinue |
    Where-Object { $_ -match 'Whisper|VAD|transcrib' } |
    Select-Object -Last 8

if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
"stopped pid $($proc.Id)"
