Set-Location 'D:/scrape_videos/scrape_videos/scrape/scrape/my_app/scrape'
$wav = Join-Path (Get-Location) 'build\speech.wav'
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SetOutputToWaveFile($wav)
$synth.Speak('play some techno from the library')
$synth.Dispose()
"wav: $([math]::Round((Get-Item $wav).Length/1KB,1)) KB"

"--- worker route ---"
& curl.exe -s --max-time 60 -X POST 'https://browser.bpiersing.workers.dev/api/transcribe' `
    -H 'Content-Type: audio/wav' --data-binary "@$wav"
''
