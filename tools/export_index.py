"""Refresh the committed video index from the live database.

The app reads ../video_index.db at runtime, but the repo also carries a
snapshot (data/video_index.db) and a JSON copy used by the static site
(public/data/videos.json). Run this after scraping so all three agree:

    .venv\\Scripts\\python tools\\export_index.py
"""

import json
import os
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE_DB = os.path.join(ROOT, "..", "video_index.db")
SNAPSHOT_DB = os.path.join(ROOT, "data", "video_index.db")
STATIC_JSON = os.path.join(ROOT, "public", "data", "videos.json")


def main():
    if not os.path.exists(LIVE_DB):
        raise SystemExit("Live database not found: %s" % LIVE_DB)

    os.makedirs(os.path.dirname(SNAPSHOT_DB), exist_ok=True)
    os.makedirs(os.path.dirname(STATIC_JSON), exist_ok=True)

    # backup() copies a consistent database even while the app is running.
    live = sqlite3.connect(LIVE_DB)
    snapshot = sqlite3.connect(SNAPSHOT_DB)
    live.backup(snapshot)
    live.close()

    rows = snapshot.execute(
        "SELECT url, title, description, thumbnail, duration, source, click_count, tags FROM videos"
    ).fetchall()
    videos = [
        {"u": url, "t": title or "", "d": description or "", "th": thumbnail or "",
         "du": duration or "", "s": source or "", "c": clicks or 0, "tg": tags or ""}
        for (url, title, description, thumbnail, duration, source, clicks, tags) in rows
    ]
    searches = snapshot.execute("SELECT COUNT(*) FROM search_history").fetchone()[0]
    clicks = snapshot.execute("SELECT SUM(click_count) FROM videos").fetchone()[0] or 0
    snapshot.close()

    payload = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "count": len(videos),
        "searches": searches,
        "clicks": clicks,
        "videos": videos,
    }
    with open(STATIC_JSON, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), ensure_ascii=False)

    print("videos %d | sources %d | searches %d | clicks %d"
          % (len(videos), len({v["s"] for v in videos}), searches, clicks))
    print("wrote %s (%.1f KB) and %s (%.1f KB)"
          % (os.path.relpath(SNAPSHOT_DB, ROOT), os.path.getsize(SNAPSHOT_DB) / 1024,
             os.path.relpath(STATIC_JSON, ROOT), os.path.getsize(STATIC_JSON) / 1024))


if __name__ == "__main__":
    main()
