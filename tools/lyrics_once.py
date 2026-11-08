"""Ask the local lyric model for one set of lyrics and print what comes back.

    .venv\\Scripts\\python tools\\lyrics_once.py
    .venv\\Scripts\\python tools\\lyrics_once.py --direct   # 8090, no Flask proxy
"""

import argparse
import json
import time
import urllib.error
import urllib.request

CORPUS = [
    'nights in the city', 'machines hum', 'cold steel', 'hold the line',
    'empty platform', 'rain on the window', 'a letter never sent',
    'the long shift', 'neon', 'distance',
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:5001')
    parser.add_argument('--genre', default='techno')
    parser.add_argument('--direct', action='store_true')
    args = parser.parse_args()
    base = 'http://127.0.0.1:8090' if args.direct else args.base

    body = {
        'genre': args.genre,
        'subject': ', '.join(CORPUS),
        'corpus': CORPUS,
        'angle': 'a worker finishing a long shift',
        'seed': 20261108,
        'avoid': [],
    }
    request = urllib.request.Request(
        base + '/api/lyrics',
        data=json.dumps(body).encode(),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            data = json.loads(response.read().decode())
            print('http', response.status, 'in', round(time.time() - started, 1), 's')
    except urllib.error.HTTPError as exc:
        print('http error', exc.code, 'in', round(time.time() - started, 1), 's')
        print(exc.read().decode()[:2000])
        raise SystemExit(1)
    except Exception as exc:  # noqa: BLE001
        print('failed after', round(time.time() - started, 1), 's:', exc)
        raise SystemExit(1)

    print('model:', data.get('model'))
    lines = data.get('lines') or []
    print(f'{len(lines)} lines')
    for line in lines:
        print(' ', line)
    if data.get('error'):
        print('error:', data['error'])


if __name__ == '__main__':
    main()
