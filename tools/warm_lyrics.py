"""Ask the local song service for one lyric set, so the model is already loaded.

    .venv\\Scripts\\python tools\\warm_lyrics.py

The first request after the service starts pays for loading Qwen (a minute or
two); this makes that happen before anyone presses the button in the page.
"""
import json
import urllib.request

payload = json.dumps({'genre': 'dubstep', 'subject': 'bass, night, city', 'seed': 3}).encode()
request = urllib.request.Request(
    'http://127.0.0.1:8090/api/lyrics',
    data=payload,
    headers={'Content-Type': 'application/json'},
)
with urllib.request.urlopen(request, timeout=600) as response:
    body = json.loads(response.read().decode())
print('\n'.join(body.get('lines', [])) or body)
