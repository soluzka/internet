"""Generate one lyric set and write it to logs/lyrics_out.txt.

Kept as a file so the arguments survive PowerShell quoting; the CLI in
lyrics.py is for people typing the command themselves.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lyrics import Lyricist, load_manifest, lyrics_model_id  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
genre = os.environ.get('LYRIC_GENRE', 'techno')
subject = os.environ.get('LYRIC_SUBJECT', 'bass night city rain')
seed = int(os.environ.get('LYRIC_SEED', '7'))

print('model:', lyrics_model_id(load_manifest()), flush=True)
lyricist = Lyricist(lyrics_model_id(load_manifest()))
lines = lyricist.write(genre, subject, seed)
with open(os.path.join(HERE, 'logs', 'lyrics_out.txt'), 'w', encoding='utf-8') as handle:
    handle.write('\n'.join(lines))
print('wrote', len(lines), 'lines', flush=True)
