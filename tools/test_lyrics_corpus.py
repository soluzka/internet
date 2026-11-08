"""Write lyrics from a corpus and check they are not about the collection.

    song_service\\.venv\\Scripts\\python tools\\test_lyrics_corpus.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'song_service'))

from lyrics import BANNED, Lyricist, load_manifest, lyrics_model_id  # noqa: E402

corpus = [
    'midnight drive', 'concrete', 'hard rain', 'northbound', 'empty platform',
    'bass weight', 'city lights', 'cold hands', 'night shift', 'steel',
]

lyricist = Lyricist(lyrics_model_id(load_manifest()))
lines = lyricist.write('industrial techno', 'machines, night shift, rain', 12, corpus=corpus)
print('\n'.join(lines))

hits = [line for line in lines if BANNED.search(line)]
print('\nlines:', len(lines), 'collection references:', len(hits))
if hits:
    print('OFFENDERS:', hits)
    raise SystemExit(1)
