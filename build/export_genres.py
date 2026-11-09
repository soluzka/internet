"""Move the inferred genre from videos.json into the database.

The genre is the one thing the site had that the database did not: genre_model.py
wrote it into the JSON export as `g`, so 1,542 of 8,724 videos carry a name and a
confidence. The cards use it, and the song designer builds its whole summary out
of it, so the database needs the same column.
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SOURCE = os.path.join(ROOT, 'public', 'data', 'videos.json')
TARGET = os.path.join(HERE, 'd1_genres.sql')


def quote(text):
    return "'" + str(text).replace("'", "''") + "'"


with open(SOURCE, encoding='utf-8') as handle:
    doc = json.load(handle)

lines = []
for video in doc.get('videos') or []:
    genre = video.get('g')
    if not genre or not genre.get('n'):
        continue
    payload = json.dumps(genre, ensure_ascii=False, separators=(',', ':'))
    lines.append('UPDATE videos SET genre_json = %s WHERE url = %s;'
                 % (quote(payload), quote(video.get('u'))))

with open(TARGET, 'w', encoding='utf-8', newline='\n') as out:
    out.write('\n'.join(lines) + '\n')

print('wrote', TARGET, 'updates:', len(lines))
print('size KB:', round(os.path.getsize(TARGET) / 1024, 1))
