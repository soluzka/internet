"""Submit one short ACE-Step job and report exactly what happens.

    .venv\\Scripts\\python tools\\ace_once.py

Prints the queue response, every status poll, and either the saved wav path or
the error the service reported.
"""

import json
import os
import time
import urllib.request

BASE = 'http://127.0.0.1:8090'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'song_service', 'logs', 'ace_once.wav')

LYRICS = 'machines hum under moonlight\ncold steel against my hands\nhold the quiet, hold the line'

request = urllib.request.Request(
    BASE + '/api/song',
    data=json.dumps({
        'prompt': 'industrial techno, distorted bass, driving drums, 120 bpm, sung vocal',
        'lyrics': LYRICS,
        'seconds': 8,
        'steps': 6,
        'seed': 4242,
    }).encode(),
    headers={'Content-Type': 'application/json'},
)
with urllib.request.urlopen(request, timeout=120) as response:
    job = json.loads(response.read().decode())
print('queued:', job, flush=True)

token = job.get('token')
if not token:
    raise SystemExit('no token: ' + json.dumps(job))

status = {}
deadline = time.time() + 45 * 60
while time.time() < deadline:
    time.sleep(5)
    try:
        with urllib.request.urlopen(BASE + '/api/song/' + token, timeout=60) as response:
            status = json.loads(response.read().decode())
    except Exception as exc:  # noqa: BLE001 - the status call itself can fail
        print('status poll failed:', exc, flush=True)
        continue
    print('status:', status, flush=True)
    if status.get('status') in ('complete', 'error'):
        break

if status.get('status') != 'complete':
    raise SystemExit('job did not complete: ' + json.dumps(status)[:500])

with urllib.request.urlopen(BASE + '/song_file/' + token, timeout=300) as response:
    audio = response.read()
with open(OUT, 'wb') as handle:
    handle.write(audio)
print('saved', len(audio), 'bytes to', OUT, flush=True)
