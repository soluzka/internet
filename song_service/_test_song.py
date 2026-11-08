"""Ask the local service for lyrics, then one sung song, and save the wav.

    song_service\\.venv\\Scripts\\python _test_song.py

Kept as a file so arguments survive shell quoting. Progress is printed so the
GPU load and the generation can both be watched from a log.
"""

import json
import os
import time
import urllib.request

BASE = os.environ.get('SONG_BASE', 'http://127.0.0.1:8090')
HERE = os.path.dirname(os.path.abspath(__file__))
SECONDS = float(os.environ.get('SONG_SECONDS', '30'))
STEPS = int(os.environ.get('SONG_STEPS', '20'))


def post(path, payload, timeout=1800):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def get(path, timeout=120):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as response:
        return json.loads(response.read().decode())


print('asking for lyrics...', flush=True)
written = post('/api/lyrics', {'genre': 'industrial', 'subject': 'machines, night shift, rain', 'seed': 5})
lines = written.get('lines') or []
print('lyrics model:', written.get('model'), flush=True)
print('\n'.join(lines), flush=True)
if len(lines) < 4:
    raise SystemExit('no usable lyrics')

print('\nqueueing the song...', flush=True)
job = post('/api/song', {
    'prompt': 'industrial, heavy distorted bass, driving drums, 110 bpm, sung male vocal',
    'lyrics': '\n'.join(lines),
    'seconds': SECONDS,
    'steps': STEPS,
})
print('job:', job, flush=True)
token = job.get('token')
if not token:
    raise SystemExit('no token')

status = job
while True:
    time.sleep(5)
    status = get('/api/song/' + token)
    print(status, flush=True)
    if status.get('status') in ('complete', 'error'):
        break

if status.get('status') != 'complete':
    raise SystemExit('generation failed')

with urllib.request.urlopen(BASE + '/song_file/' + token, timeout=600) as response:
    audio = response.read()
target = os.path.join(HERE, 'logs', 'first-sung.wav')
with open(target, 'wb') as handle:
    handle.write(audio)
print(f'\nsaved {len(audio)} bytes to {target}', flush=True)
