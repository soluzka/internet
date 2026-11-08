"""Ask for three lyric sets in a row and compare them.

    .venv\\Scripts\\python tools\\lyrics_variety.py

Mimics the page: each request carries the previous lines as "avoid", so a repeat
should be filtered out server-side.
"""

import json
import re
import urllib.request

BASE = 'http://127.0.0.1:8090'
CORPUS = ['midnight drive', 'concrete', 'hard rain', 'northbound', 'empty platform',
          'cold hands', 'night shift', 'steel', 'overpass', 'broken glass']
ANGLES = ['second person, walking at night', 'first person leaving a city for good',
          'a letter that was never sent']

previous = []
sets = []
for index, seed in enumerate([11, 22, 33]):
    payload = json.dumps({
        'genre': 'industrial techno',
        'corpus': CORPUS,
        'corpus_seed': seed,
        'angle': ANGLES[index % len(ANGLES)],
        'seed': seed,
        'avoid': previous,
    }).encode()
    request = urllib.request.Request(BASE + '/api/lyrics', data=payload,
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=900) as response:
        body = json.loads(response.read().decode())
    lines = body.get('lines') or []
    sets.append(lines)
    previous = (previous + lines)[-14:]
    print(f'--- seed {seed} ({len(lines)} lines) ---')
    print('\n'.join(lines))
    print()


def normal(line):
    return set(re.sub(r'[^a-z0-9 ]', '', line.lower()).split())


for a in range(len(sets)):
    for b in range(a + 1, len(sets)):
        repeats = 0
        for line in sets[b]:
            words = normal(line)
            if any(words and normal(other) and len(words & normal(other)) / max(len(words), len(normal(other))) >= 0.75
                   for other in sets[a]):
                repeats += 1
        print(f'set {a + 1} vs {b + 1}: {repeats} repeated lines')
