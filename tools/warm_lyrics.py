"""Ask the local service for lyrics from a corpus and check what comes back.

    .venv\\Scripts\\python tools\\warm_lyrics.py

Works on the real HTTP path the page uses, so it tests the route, the prompt and
the filter together. Also warms the model, which otherwise takes a minute on the
first request after the service starts.
"""

import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'song_service'))

from lyrics import BANNED  # noqa: E402

CORPUS = [
    'midnight drive', 'concrete', 'hard rain', 'northbound', 'empty platform',
    'bass weight', 'city lights', 'cold hands', 'night shift', 'steel',
    'overpass', 'static hiss', 'long walk home', 'broken glass',
]

payload = json.dumps({
    'genre': 'industrial techno',
    'subject': 'machines, night shift, rain',
    'corpus': CORPUS,
    'seed': 12,
}).encode()

request = urllib.request.Request(
    'http://127.0.0.1:8090/api/lyrics',
    data=payload,
    headers={'Content-Type': 'application/json'},
)
with urllib.request.urlopen(request, timeout=900) as response:
    body = json.loads(response.read().decode())

lines = body.get('lines') or []
print('\n'.join(lines))
hits = [line for line in lines if BANNED.search(line)]
print(f"\nmodel: {body.get('model')}")
print(f'lines: {len(lines)}  collection references: {len(hits)}')
if hits:
    print('OFFENDERS:', hits)
    raise SystemExit(1)
