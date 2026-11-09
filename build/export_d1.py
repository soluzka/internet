"""Turn data/video_index.db into one SQL file for `wrangler d1 execute --file`.

sqlite3's own dump is used for the escaping - it is the only thing that gets
quotes, newlines and unicode right for every row - with the transaction control
statements dropped: D1 runs each batch in its own transaction and refuses a
BEGIN inside one.
"""

import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SOURCE = os.path.join(ROOT, 'data', 'video_index.db')
TARGET = os.path.join(HERE, 'd1_import.sql')

SKIP = ('BEGIN TRANSACTION;', 'COMMIT;')

with open(TARGET, 'w', encoding='utf-8', newline='\n') as out:
    db = sqlite3.connect(SOURCE)
    statements = 0
    rows = 0
    for line in db.iterdump():
        text = line.strip()
        if not text or text in SKIP:
            continue
        # AUTOINCREMENT bookkeeping belongs to the old database, not this one.
        if text.startswith('INSERT INTO sqlite_sequence'):
            continue
        out.write(line)
        out.write('\n')
        statements += 1
        if text.startswith('INSERT INTO'):
            rows += 1

    # Search is a LIKE scan over 8,724 rows, which is cheap, but the ordering by
    # clicks and the exact-url lookups are worth an index.
    out.write('CREATE INDEX IF NOT EXISTS idx_videos_click ON videos(click_count DESC);\n')
    out.write('CREATE INDEX IF NOT EXISTS idx_prefs_query ON learned_preferences(query);\n')

print('wrote', TARGET)
print('statements:', statements, 'insert rows:', rows)
print('size MB:', round(os.path.getsize(TARGET) / 1024 / 1024, 2))
