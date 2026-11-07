"""
AI Video Search Engine
======================
An AI-powered video search engine with machine learning ranking,
autonomous discovery agents, and voice assistant support.

Components:
    - VideoScraper: Collects videos from multiple platforms using lxml
    - MLDatabase: Stores and searches videos using TF-IDF + cosine similarity
    - DiscoveryAgent: AI agent that discovers new video content
    - RankingAgent: AI agent that ranks results by relevance
    - VoiceAssistant: Voice input/output interface
    - DownloadManager: Downloads videos with yt-dlp
"""

import os
import re
import json
import random
import shutil
import asyncio
import logging
import tempfile
import threading
import sqlite3
import hashlib
import time
import base64
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urljoin, quote, urlparse, parse_qs, unquote

import aiohttp
import requests
import yt_dlp
from lxml import html as lxml_html
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.decomposition import TruncatedSVD
import numpy as np
from flask import send_file, jsonify, request
from flask_socketio import emit

from genre_model import MusicGenreModel

# Locate ffmpeg for yt-dlp merging
try:
    import imageio_ffmpeg
    FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_PATH = 'ffmpeg'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# DATABASE SCHEMA
# ============================================================================

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'video_index.db')

# Discovery writes while searches read and log. SQLite's default 5 s lock wait
# was too short, so a busy database surfaced as "Search Error: database is
# locked" and threw away a search that had already found its results.
DB_TIMEOUT = 30.0


def connect_db(db_path: str) -> sqlite3.Connection:
    """Open the index database with a lock wait long enough to queue, not fail."""
    conn = sqlite3.connect(db_path, timeout=DB_TIMEOUT)
    conn.execute('PRAGMA busy_timeout = %d' % int(DB_TIMEOUT * 1000))
    return conn


def log_search(db_path: str, query: str, count: int) -> None:
    """Record a search. Best effort: this must never fail the search itself."""
    try:
        conn = connect_db(db_path)
        try:
            conn.execute(
                "INSERT INTO search_history (query, result_count, searched_at) VALUES (?, ?, ?)",
                (query, count, time.time())
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.warning(f'Could not log search {query!r}: {exc}')

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    thumbnail TEXT,
    duration TEXT,
    source TEXT,
    platform TEXT,
    discovered_at REAL DEFAULT 0,
    click_count INTEGER DEFAULT 0,
    relevance_score REAL DEFAULT 0,
    tags TEXT
);

CREATE TABLE IF NOT EXISTS search_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    result_count INTEGER DEFAULT 0,
    searched_at REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS learned_preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    clicked_url TEXT NOT NULL,
    clicked_title TEXT,
    learned_at REAL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_videos_url ON videos(url);
CREATE INDEX IF NOT EXISTS idx_videos_source ON videos(source);
CREATE INDEX IF NOT EXISTS idx_search_history_query ON search_history(query);
"""


class MLDatabase:
    """Machine learning powered video database with TF-IDF search."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
        self._init_db()
        self.vectorizer = TfidfVectorizer(
            max_features=5000,
            stop_words='english',
            ngram_range=(1, 2),
            lowercase=True,
        )
        self.tfidf_matrix = None
        self.video_ids = []
        self.documents = []
        self.svd = None
        self.svd_matrix = None
        # Set by setup_routes once the library is loaded, so search results can
        # carry the genre the listing argues for.
        self.genre_model = None
        self._rebuild_index()

    def _init_db(self):
        """Initialize the SQLite database."""
        conn = connect_db(self.db_path)
        try:
            # WAL lets searches read while discovery is writing, and keeps
            # writers queued on the busy timeout instead of erroring out.
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=NORMAL')
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()
        logger.info(f"Database initialized at {self.db_path}")

    def _rebuild_index(self):
        """Rebuild the TF-IDF index from stored videos."""
        conn = connect_db(self.db_path)
        rows = conn.execute(
            "SELECT id, title, description, tags FROM videos ORDER BY id"
        ).fetchall()
        conn.close()

        if not rows:
            logger.info("No videos in database yet, index empty")
            self.tfidf_matrix = None
            self.video_ids = []
            self.documents = []
            return

        self.video_ids = [r[0] for r in rows]
        documents = []
        for r in rows:
            doc = f"{r[1] or ''} {r[2] or ''} {r[3] or ''}"
            documents.append(doc)

        # Kept for deciding what actually matches. Ranking uses the ML scores,
        # but "is this a match" has to be a fact, not a similarity threshold
        # that swings every time the index is rebuilt.
        self.documents = [doc.lower() for doc in documents]

        self.tfidf_matrix = self.vectorizer.fit_transform(documents)

        # Build LSA (Latent Semantic Analysis) for better semantic matching
        n_components = min(100, len(documents) - 1, self.tfidf_matrix.shape[1] - 1)
        if n_components > 1:
            try:
                self.svd = TruncatedSVD(n_components=n_components, random_state=42)
                self.svd_matrix = self.svd.fit_transform(self.tfidf_matrix)
                # Verify the SVD was properly fitted
                if not hasattr(self.svd, 'components_') or self.svd.components_ is None:
                    self.svd = None
                    self.svd_matrix = None
            except Exception as e:
                logger.warning(f'SVD failed, falling back to TF-IDF only: {e}')
                self.svd = None
                self.svd_matrix = None
        else:
            self.svd = None
            self.svd_matrix = None

        logger.info(f"ML index rebuilt: {len(documents)} videos, {self.tfidf_matrix.shape[1]} features")

    def add_video(self, url: str, title: str, description: str = '',
                  thumbnail: str = '', duration: str = 'Unknown',
                  source: str = 'Unknown', platform: str = 'Unknown',
                  tags: str = '') -> bool:
        """Add a video to the database. Returns True if new, False if duplicate."""
        conn = connect_db(self.db_path)
        try:
            conn.execute(
                """INSERT OR IGNORE INTO videos
                   (url, title, description, thumbnail, duration, source, platform, discovered_at, tags)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (url, title, description, thumbnail, duration, source, platform, time.time(), tags)
            )
            conn.commit()
            changed = conn.total_changes > 0
        finally:
            conn.close()
        return changed

    def similarities(self, query: str) -> Optional[np.ndarray]:
        """Similarity score of every indexed video for a query."""
        if self.tfidf_matrix is None or not self.video_ids:
            return None

        # Transform query into TF-IDF space
        query_vec = self.vectorizer.transform([query])

        # Compute cosine similarity
        sims = cosine_similarity(query_vec, self.tfidf_matrix).flatten()

        # If LSA is available, also compute semantic similarity
        if self.svd is not None and self.svd_matrix is not None:
            try:
                query_svd = self.svd.transform(query_vec)
                svd_sims = cosine_similarity(query_svd, self.svd_matrix).flatten()
                # Combine: 70% TF-IDF + 30% LSA semantic
                sims = 0.7 * sims + 0.3 * svd_sims
            except Exception as e:
                logger.warning(f'SVD search failed, using TF-IDF only: {e}')
        return sims

    def match_mask(self, query: str) -> Optional[np.ndarray]:
        """Boolean mask of videos whose text contains at least one query term."""
        terms = [t for t in re.findall(r"[a-z0-9']+", (query or '').lower()) if len(t) > 1]
        if not terms or not self.documents:
            return None
        mask = np.zeros(len(self.documents), dtype=bool)
        for index, doc in enumerate(self.documents):
            for term in terms:
                if term in doc:
                    mask[index] = True
                    break
        return mask

    def count_matches(self, query: str) -> int:
        """How many videos actually match, ignoring any result limit."""
        mask = self.match_mask(query)
        if mask is None:
            return 0
        return int(np.count_nonzero(mask))

    def search(self, query: str, limit: int = None) -> List[Dict]:
        """Search the database using ML (TF-IDF + LSA + cosine similarity).

        Returns every matching video; pass a limit only to ask for a subset.
        """
        sims = self.similarities(query)
        if sims is None:
            return []

        # Only videos that actually contain the query terms count as matches;
        # the ML score decides their order, not whether they belong.
        mask = self.match_mask(query)
        if mask is None:
            return []
        top_indices = np.flatnonzero(mask)
        if top_indices.size == 0:
            return []
        top_indices = top_indices[np.argsort(sims[top_indices])[::-1]]
        if limit:
            top_indices = top_indices[:limit]

        conn = connect_db(self.db_path)
        results = []
        for idx in top_indices:
            vid_id = self.video_ids[idx]
            row = conn.execute(
                """SELECT url, title, description, thumbnail, duration, source, platform,
                          click_count, tags
                   FROM videos WHERE id = ?""", (vid_id,)
            ).fetchone()
            if row:
                result = {
                    'url': row[0],
                    'title': row[1],
                    'description': row[2] or '',
                    'thumbnail': row[3] or '',
                    'duration': row[4] or 'Unknown',
                    'source': row[5] or 'Unknown',
                    'platform': row[6] or 'Unknown',
                    'type': 'video',
                    'score': max(float(sims[idx]), 0.0),
                    'click_count': row[7],
                }
                if self.genre_model is not None:
                    try:
                        genre = self.genre_model.infer(row[1], row[2], row[8])
                    except Exception as genre_err:  # never let a guess break search
                        logger.warning(f'Genre inference failed for {row[0]!r}: {genre_err}')
                        genre = None
                    if genre:
                        result['genre'] = genre
                results.append(result)
            if limit and len(results) >= limit:
                break
        conn.close()
        return results

    def record_click(self, query: str, url: str, title: str = ''):
        """Record that user clicked a result - the ML learns from this."""
        conn = connect_db(self.db_path)
        conn.execute(
            "UPDATE videos SET click_count = click_count + 1 WHERE url = ?",
            (url,)
        )
        conn.execute(
            """INSERT INTO learned_preferences (query, clicked_url, clicked_title, learned_at)
               VALUES (?, ?, ?, ?)""",
            (query, url, title, time.time())
        )
        conn.execute(
            """INSERT INTO search_history (query, result_count, searched_at)
               VALUES (?, ?, ?)""",
            (query, 0, time.time())
        )
        conn.commit()
        conn.close()
        logger.info(f"Learned preference: query='{query}' clicked='{title}'")

    def get_stats(self) -> Dict:
        """Get database statistics."""
        conn = connect_db(self.db_path)
        try:
            total = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
            by_source = conn.execute(
                "SELECT source, COUNT(*) FROM videos GROUP BY source ORDER BY COUNT(*) DESC"
            ).fetchall()
            searches = conn.execute("SELECT COUNT(*) FROM search_history").fetchone()[0]
            clicks = conn.execute("SELECT COUNT(*) FROM learned_preferences").fetchone()[0]
        finally:
            conn.close()
        return {
            'total_videos': total,
            'by_source': dict(by_source),
            'total_searches': searches,
            'total_clicks': clicks,
        }

    def rebuild(self):
        """Rebuild the ML index."""
        self._rebuild_index()


# ============================================================================
# VIDEO SCRAPER - Collects videos using lxml (no BS4)
# ============================================================================

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}

# Shorter timeout on Render's free tier for faster response
REQUEST_TIMEOUT = 8 if os.environ.get('RENDER') else 15


def _env_int(name: str, default: int, minimum: int) -> int:
    """Read a positive int from the environment, falling back on bad input."""
    try:
        return max(minimum, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


# How deep each source pages during discovery. Deeper paging is what makes the
# index grow toward what you actually search for, at the cost of slower
# searches; override with SCRAPE_DEPTH / DAILYMOTION_DEPTH when needed.
SCRAPE_DEPTH = _env_int('SCRAPE_DEPTH', 200, 25)
DAILYMOTION_DEPTH = _env_int('DAILYMOTION_DEPTH', 200, 50)
DISCOVERY_TIMEOUT_DEFAULT = float(os.environ.get('DISCOVERY_TIMEOUT', 75))

# Supported video URL patterns for extraction
VIDEO_URL_PATTERNS = [
    r'https?://(?:www\.)?youtube\.com/watch\?v=[a-zA-Z0-9_-]{11}',
    r'https?://(?:www\.)?youtu\.be/[a-zA-Z0-9_-]{11}',
    r'https?://(?:www\.)?youtube\.com/embed/[a-zA-Z0-9_-]{11}',
    r'https?://(?:www\.)?youtube\.com/shorts/[a-zA-Z0-9_-]{11}',
    r'https?://(?:www\.)?tiktok\.com/@[\w.-]+/video/\d+',
    r'https?://vm\.tiktok\.com/[a-zA-Z0-9]+',
    r'https?://(?:www\.)?dailymotion\.com/video/[a-zA-Z0-9]+',
    r'https?://dai\.ly/[a-zA-Z0-9]+',
    r'https?://(?:www\.)?vimeo\.com/\d+',
    r'https?://(?:www\.)?instagram\.com/(?:reel|p)/[a-zA-Z0-9_-]+',
    r'https?://(?:www\.)?(?:twitter|x)\.com/\w+/status/\d+',
    r'https?://(?:www\.)?facebook\.com/(?:watch\?v=|reel/)\d+',
    r'https?://(?:www\.)?twitch\.tv/\w+/clip/[a-zA-Z0-9_-]+',
    r'https?://(?:www\.)?streamable\.com/[a-zA-Z0-9]+',
    r'https?://(?:www\.)?bilibili\.com/video/[a-zA-Z0-9]+',
]

PLATFORM_NAMES = [
    ('youtube.com', 'YouTube'), ('youtu.be', 'YouTube'),
    ('tiktok.com', 'TikTok'), ('vm.tiktok.com', 'TikTok'),
    ('dailymotion.com', 'Dailymotion'), ('dai.ly', 'Dailymotion'),
    ('vimeo.com', 'Vimeo'),
    ('instagram.com', 'Instagram'),
    ('twitter.com', 'Twitter'), ('x.com', 'Twitter'),
    ('facebook.com', 'Facebook'),
    ('twitch.tv', 'Twitch'),
    ('streamable.com', 'Streamable'),
    ('bilibili.com', 'Bilibili'),
]


def detect_platform(url: str) -> str:
    """Detect the platform name from a URL."""
    if not url:
        return 'Unknown'
    url_lower = url.lower()
    for domain, name in PLATFORM_NAMES:
        if domain in url_lower:
            return name
    if 'bing.com' in url_lower or 'bing.co.uk' in url_lower:
        return 'Bing'
    # Extract domain name for websites
    try:
        netloc = urlparse(url).netloc.replace('www.', '')
        if netloc:
            return netloc.split('.')[0].capitalize()
    except Exception:
        pass
    return 'Unknown'


def favicon_url(url: str) -> str:
    """Return a favicon URL for a given page using Google's favicon service."""
    try:
        domain = urlparse(url).netloc
        if domain:
            return f'https://www.google.com/s2/favicons?domain={domain}&sz=128'
    except Exception:
        pass
    return ''


def decode_bing_redirect(url: str) -> str:
    """Unwrap a Bing click-tracking URL to get the real destination."""
    try:
        parsed = urlparse(url)
        if 'bing.com' not in parsed.netloc.lower():
            return url
        qs = parse_qs(parsed.query)
        u = qs.get('u', [''])[0]
        if u:
            if u.startswith('a1'):
                u = u[2:]
            decoded = base64.urlsafe_b64decode(u + '==').decode('utf-8', errors='ignore')
            if decoded.startswith('http'):
                return decoded
    except Exception:
        pass
    return url


def is_video_url(url: str) -> bool:
    """Return True if the URL points to a known video/audio host."""
    if not url:
        return False
    video_hosts = {
        'youtube.com', 'youtu.be', 'm.youtube.com',
        'tiktok.com', 'vm.tiktok.com',
        'dailymotion.com', 'dai.ly',
        'vimeo.com',
        'instagram.com',
        'twitter.com', 'x.com',
        'facebook.com', 'fb.watch',
        'twitch.tv',
        'streamable.com',
        'bilibili.com',
        'rumble.com',
        'odysee.com',
        'reddit.com', 'redd.it',
    }
    netloc = urlparse(url).netloc.lower()
    return any(host in netloc for host in video_hosts)


def extract_video_urls(text: str) -> List[str]:
    """Extract all supported video URLs from text."""
    urls = []
    seen = set()
    for pattern in VIDEO_URL_PATTERNS:
        for match in re.finditer(pattern, text):
            url = match.group(0)
            if url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


class VideoScraper:
    """Scrapes video content from multiple platforms using lxml."""

    def __init__(self):
        self.headers = BROWSER_HEADERS

    async def search_all(self, query: str, socketio=None) -> List[Dict]:
        """Search all platforms concurrently and return combined results."""
        # On Render (slow free tier), search fewer sources for speed
        is_render = os.environ.get('RENDER')
        if is_render:
            tasks = [
                self._search_youtube(query, socketio),
                self._search_dailymotion(query, socketio),
                self._search_bing_videos(query, socketio),
                self._search_bing_web(query, socketio),
            ]
        else:
            tasks = [
                self._search_youtube(query, socketio),
                self._search_youtube_mobile(query, socketio),
                self._search_dailymotion(query, socketio),
                self._search_bing_videos(query, socketio),
                self._search_bing_videos_uk(query, socketio),
                self._search_bing_web(query, socketio),
                self._search_bing_web_uk(query, socketio),
                self._search_duckduckgo(query, socketio),
            ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_results = []
        for r in results:
            if isinstance(r, list):
                all_results.extend(r)
            elif isinstance(r, Exception):
                logger.error(f"Search error: {r}")

        # Deduplicate by URL
        seen_urls = set()
        unique = []
        for v in all_results:
            if v['url'] not in seen_urls:
                seen_urls.add(v['url'])
                unique.append(v)

        random.shuffle(unique)
        return unique

    async def _search_youtube(self, query: str, socketio=None) -> List[Dict]:
        """Search YouTube desktop for videos."""
        results = []
        try:
            search_url = f'https://www.youtube.com/results?search_query={quote(query)}'
            logger.info(f'YouTube search: {search_url}')

            async with aiohttp.ClientSession() as session:
                async with session.get(search_url, headers=self.headers) as response:
                    if response.status != 200:
                        return results
                    html_text = await response.text()

            # Extract video IDs using regex (YouTube embeds data in JSON)
            video_ids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', html_text)
            video_titles = re.findall(r'"title":{"runs":\[{"text":"([^"]+)"}]}', html_text)
            video_durations = re.findall(r'"simpleText":"([0-9:]+)"', html_text)

            seen = set()
            for i, vid_id in enumerate(video_ids):
                if vid_id in seen or len(results) >= SCRAPE_DEPTH:
                    continue
                seen.add(vid_id)

                title = video_titles[i] if i < len(video_titles) else 'Untitled Video'
                duration = video_durations[i] if i < len(video_durations) else 'Unknown'

                results.append({
                    'url': f'https://www.youtube.com/watch?v={vid_id}',
                    'title': title,
                    'description': f'YouTube video: {title}',
                    'thumbnail': f'https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg',
                    'duration': duration,
                    'source': 'YouTube',
                    'platform': 'YouTube',
                })

                if socketio:
                    socketio.emit('new_result', {
                        'result': results[-1]
                    })

        except Exception as e:
            logger.error(f'YouTube search error: {e}')
        return results

    async def _search_youtube_mobile(self, query: str, socketio=None) -> List[Dict]:
        """Search YouTube mobile for videos."""
        results = []
        try:
            search_url = f'https://m.youtube.com/results?search_query={quote(query)}'
            logger.info(f'YouTube Mobile search: {search_url}')

            async with aiohttp.ClientSession() as session:
                async with session.get(search_url, headers=self.headers) as response:
                    if response.status != 200:
                        return results
                    html_text = await response.text()

            video_ids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', html_text)
            video_titles = re.findall(r'"title":"([^"]+)"', html_text)

            seen = set()
            for i, vid_id in enumerate(video_ids):
                if vid_id in seen or len(results) >= SCRAPE_DEPTH:
                    continue
                seen.add(vid_id)

                title = video_titles[i] if i < len(video_titles) else 'Untitled Video'
                results.append({
                    'url': f'https://www.youtube.com/watch?v={vid_id}',
                    'title': title,
                    'description': f'YouTube video: {title}',
                    'thumbnail': f'https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg',
                    'duration': 'Unknown',
                    'source': 'YouTube',
                    'platform': 'YouTube',
                })

                if socketio:
                    socketio.emit('new_result', {
                        'result': results[-1]
                    })

        except Exception as e:
            logger.error(f'YouTube Mobile search error: {e}')
        return results

    async def _search_dailymotion(self, query: str, socketio=None) -> List[Dict]:
        """Search Dailymotion for videos using their public JSON API.

        Pages 100 results at a time until DAILYMOTION_DEPTH is reached.
        """
        results = []
        page_size = 100
        try:
            import json as _json

            async with aiohttp.ClientSession() as session:
                for page in range(1, DAILYMOTION_DEPTH // page_size + 2):
                    if len(results) >= DAILYMOTION_DEPTH:
                        break

                    api_url = (
                        'https://api.dailymotion.com/videos?search=' + quote(query)
                        + f'&limit={page_size}&page={page}'
                        + '&fields=id,title,description,thumbnail_url,duration'
                    )
                    logger.info(f'Dailymotion API page {page}: {api_url}')

                    async with session.get(
                        api_url,
                        headers=self.headers,
                        timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                    ) as response:
                        if response.status != 200:
                            break
                        data = _json.loads(await response.text())

                    videos = data.get('list', [])
                    if not videos:
                        break

                    for v in videos:
                        vid_id = v.get('id', '')
                        if not vid_id:
                            continue
                        title = v.get('title', 'Dailymotion Video')
                        desc = v.get('description', '') or title
                        thumb = v.get('thumbnail_url', '')
                        dur = v.get('duration', 0)
                        dur_str = f'{dur // 60}:{dur % 60:02d}' if dur else 'Unknown'

                        results.append({
                            'url': f'https://www.dailymotion.com/video/{vid_id}',
                            'title': title,
                            'description': desc,
                            'thumbnail': thumb,
                            'duration': dur_str,
                            'source': 'Dailymotion',
                            'platform': 'Dailymotion',
                        })

                        if socketio:
                            socketio.emit('new_result', {'result': results[-1]})

                    if len(videos) < page_size:
                        break

        except Exception as e:
            logger.error(f'Dailymotion search error: {e}')
        return results

    async def _search_bing_videos(self, query: str, socketio=None) -> List[Dict]:
        """Search Bing Video Search - finds videos across ALL platforms (YouTube, TikTok, Dailymotion, etc.)."""
        results = []
        try:
            for offset in range(0, SCRAPE_DEPTH, 25):
                if len(results) >= SCRAPE_DEPTH:
                    break

                search_url = f'https://www.bing.com/videos/search?q={quote(query)}&first={offset}'
                logger.info(f'Bing videos offset {offset}: {search_url}')

                async with aiohttp.ClientSession() as session:
                    async with session.get(search_url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as response:
                        if response.status != 200:
                            continue
                        html_text = await response.text()

                # Parse with lxml
                tree = lxml_html.fromstring(html_text)

                # Bing video elements use class dg_u or mc_vtvc
                video_elements = tree.xpath('//div[contains(@class, "dg_u")] | //div[contains(@class, "mc_vtvc")]')
                logger.info(f'Found {len(video_elements)} video elements on Bing offset {offset}')

                for element in video_elements:
                    try:
                        if len(results) >= SCRAPE_DEPTH:
                            break

                        # Get title
                        title_elems = element.xpath('.//*[contains(@class, "mc_vtvc_title")]')
                        title = title_elems[0].text_content().strip() if title_elems else ''

                        # Get link
                        links = element.xpath('.//a/@href')
                        video_url = links[0] if links else ''

                        # Extract real video URL from element HTML (finds YouTube, TikTok, etc.)
                        el_html = lxml_html.tostring(element, encoding='unicode')
                        real_url = extract_video_urls(el_html)
                        if real_url:
                            video_url = real_url[0]
                        elif video_url and not video_url.startswith('http'):
                            video_url = f'https://www.bing.com{video_url}'

                        if not title or not video_url:
                            continue

                        # Get thumbnail
                        imgs = element.xpath('.//img/@src | .//img/@data-src')
                        thumbnail = imgs[0] if imgs else ''

                        # Get duration
                        dur_elems = element.xpath('.//*[contains(@class, "mc_vtvc_duration")]')
                        duration = dur_elems[0].text_content().strip() if dur_elems else 'Unknown'

                        # Detect the actual source platform
                        source_platform = detect_platform(video_url)

                        results.append({
                            'url': video_url,
                            'title': title,
                            'description': title,
                            'thumbnail': thumbnail,
                            'duration': duration,
                            'source': source_platform,
                            'platform': 'Bing',
                        })

                        if socketio:
                            socketio.emit('new_result', {'result': results[-1]})

                    except Exception as e:
                        logger.error(f'Error processing Bing result: {e}')

                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f'Bing videos search error: {e}')
        return results

    async def _search_bing_videos_uk(self, query: str, socketio=None) -> List[Dict]:
        """Search Bing UK Video Search - more results from all platforms."""
        results = []
        try:
            for offset in range(0, SCRAPE_DEPTH, 25):
                if len(results) >= SCRAPE_DEPTH:
                    break

                search_url = f'https://www.bing.co.uk/videos/search?q={quote(query)}&first={offset}'
                logger.info(f'Bing UK videos offset {offset}: {search_url}')

                async with aiohttp.ClientSession() as session:
                    async with session.get(search_url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as response:
                        if response.status != 200:
                            continue
                        html_text = await response.text()

                tree = lxml_html.fromstring(html_text)
                video_elements = tree.xpath('//div[contains(@class, "dg_u")] | //div[contains(@class, "mc_vtvc")]')
                logger.info(f'Found {len(video_elements)} video elements on Bing UK offset {offset}')

                for element in video_elements:
                    try:
                        if len(results) >= SCRAPE_DEPTH:
                            break

                        title_elems = element.xpath('.//*[contains(@class, "mc_vtvc_title")]')
                        title = title_elems[0].text_content().strip() if title_elems else ''

                        links = element.xpath('.//a/@href')
                        video_url = links[0] if links else ''

                        el_html = lxml_html.tostring(element, encoding='unicode')
                        real_url = extract_video_urls(el_html)
                        if real_url:
                            video_url = real_url[0]
                        elif video_url and not video_url.startswith('http'):
                            video_url = f'https://www.bing.co.uk{video_url}'

                        if not title or not video_url:
                            continue

                        imgs = element.xpath('.//img/@src | .//img/@data-src')
                        thumbnail = imgs[0] if imgs else ''

                        dur_elems = element.xpath('.//*[contains(@class, "mc_vtvc_duration")]')
                        duration = dur_elems[0].text_content().strip() if dur_elems else 'Unknown'

                        source_platform = detect_platform(video_url)

                        results.append({
                            'url': video_url,
                            'title': title,
                            'description': title,
                            'thumbnail': thumbnail,
                            'duration': duration,
                            'source': source_platform,
                            'platform': 'Bing UK',
                        })

                        if socketio:
                            socketio.emit('new_result', {'result': results[-1]})

                    except Exception as e:
                        logger.error(f'Error processing Bing UK result: {e}')

                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f'Bing UK videos search error: {e}')
        return results

    async def _search_bing_web(self, query: str, socketio=None) -> List[Dict]:
        """Search Bing Web Search - finds Reddit, websites, articles, and videos across all platforms."""
        results = []
        try:
            for offset in range(0, SCRAPE_DEPTH, 25):
                if len(results) >= SCRAPE_DEPTH:
                    break

                search_url = f'https://www.bing.com/search?q={quote(query)}&first={offset}'
                logger.info(f'Bing Web offset {offset}: {search_url}')

                async with aiohttp.ClientSession() as session:
                    async with session.get(search_url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as response:
                        if response.status != 200:
                            continue
                        html_text = await response.text()

                tree = lxml_html.fromstring(html_text)
                # Bing web results are in <li class="b_algo">
                result_items = tree.xpath('//li[contains(@class, "b_algo")]')
                logger.info(f'Found {len(result_items)} web results on Bing offset {offset}')

                for item in result_items:
                    try:
                        if len(results) >= SCRAPE_DEPTH:
                            break

                        # Get the link from h2 > a
                        h2_links = item.xpath('.//h2//a/@href | .//h2/a/@href')
                        if not h2_links:
                            h2_links = item.xpath('.//a/@href')
                        raw_url = h2_links[0] if h2_links else ''
                        if not raw_url or raw_url.startswith('/'):
                            continue

                        url = decode_bing_redirect(raw_url)
                        if not url or not url.startswith('http'):
                            continue

                        parsed_url = urlparse(url)
                        if 'bing.com' in parsed_url.netloc.lower():
                            continue

                        # Get title
                        h2_texts = item.xpath('.//h2//text() | .//h2/text()')
                        title = ''.join(h2_texts).strip() if h2_texts else ''
                        if not title:
                            continue

                        # Get snippet
                        snippets = item.xpath('.//p//text()')
                        snippet = ''.join(snippets).strip() if snippets else title

                        result_type = 'video' if is_video_url(url) else 'website'
                        source = detect_platform(url)

                        results.append({
                            'url': url,
                            'title': title,
                            'description': snippet or title,
                            'thumbnail': favicon_url(url),
                            'duration': '' if result_type != 'video' else 'Unknown',
                            'source': source,
                            'platform': 'Bing Web',
                            'type': result_type,
                        })

                        if socketio:
                            socketio.emit('new_result', {'result': results[-1]})

                    except Exception as e:
                        logger.error(f'Error processing Bing web result: {e}')

                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f'Bing web search error: {e}')
        return results

    async def _search_bing_web_uk(self, query: str, socketio=None) -> List[Dict]:
        """Search Bing UK Web Search - more Reddit, websites, articles."""
        results = []
        try:
            for offset in range(0, SCRAPE_DEPTH, 25):
                if len(results) >= SCRAPE_DEPTH:
                    break

                search_url = f'https://www.bing.co.uk/search?q={quote(query)}&first={offset}'
                logger.info(f'Bing UK Web offset {offset}: {search_url}')

                async with aiohttp.ClientSession() as session:
                    async with session.get(search_url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as response:
                        if response.status != 200:
                            continue
                        html_text = await response.text()

                tree = lxml_html.fromstring(html_text)
                result_items = tree.xpath('//li[contains(@class, "b_algo")]')
                logger.info(f'Found {len(result_items)} web results on Bing UK offset {offset}')

                for item in result_items:
                    try:
                        if len(results) >= SCRAPE_DEPTH:
                            break

                        h2_links = item.xpath('.//h2//a/@href | .//h2/a/@href')
                        if not h2_links:
                            h2_links = item.xpath('.//a/@href')
                        raw_url = h2_links[0] if h2_links else ''
                        if not raw_url or raw_url.startswith('/'):
                            continue

                        url = decode_bing_redirect(raw_url)
                        if not url or not url.startswith('http'):
                            continue

                        parsed_url = urlparse(url)
                        if 'bing.co.uk' in parsed_url.netloc.lower():
                            continue

                        h2_texts = item.xpath('.//h2//text() | .//h2/text()')
                        title = ''.join(h2_texts).strip() if h2_texts else ''
                        if not title:
                            continue

                        snippets = item.xpath('.//p//text()')
                        snippet = ''.join(snippets).strip() if snippets else title

                        result_type = 'video' if is_video_url(url) else 'website'
                        source = detect_platform(url)

                        results.append({
                            'url': url,
                            'title': title,
                            'description': snippet or title,
                            'thumbnail': favicon_url(url),
                            'duration': '' if result_type != 'video' else 'Unknown',
                            'source': source,
                            'platform': 'Bing UK Web',
                            'type': result_type,
                        })

                        if socketio:
                            socketio.emit('new_result', {'result': results[-1]})

                    except Exception as e:
                        logger.error(f'Error processing Bing UK web result: {e}')

                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f'Bing UK web search error: {e}')
        return results

    async def _search_duckduckgo(self, query: str, socketio=None) -> List[Dict]:
        """Search DuckDuckGo HTML search - finds Reddit, forums, websites."""
        results = []
        try:
            for offset in range(0, SCRAPE_DEPTH, 30):
                if len(results) >= SCRAPE_DEPTH:
                    break

                search_url = f'https://html.duckduckgo.com/html/?q={quote(query)}&s={offset}'
                logger.info(f'DuckDuckGo offset {offset}: {search_url}')

                async with aiohttp.ClientSession() as session:
                    async with session.get(search_url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as response:
                        if response.status != 200:
                            continue
                        html_text = await response.text()

                tree = lxml_html.fromstring(html_text)
                # DuckDuckGo results are in div.result
                result_items = tree.xpath('//div[contains(@class, "result")] | //div[contains(@class, "web-result")]')
                logger.info(f'Found {len(result_items)} results on DuckDuckGo offset {offset}')

                for item in result_items:
                    try:
                        if len(results) >= SCRAPE_DEPTH:
                            break

                        # Get link
                        links = item.xpath('.//a[contains(@class, "result__a")]/@href | .//a[@class="result__url"]/@href')
                        if not links:
                            links = item.xpath('.//h2//a/@href')
                        raw_url = links[0] if links else ''
                        if not raw_url:
                            continue

                        # Decode DuckDuckGo redirect
                        if 'duckduckgo.com' in raw_url:
                            parsed = urlparse(raw_url)
                            qs = parse_qs(parsed.query)
                            uddg = qs.get('uddg', [''])[0]
                            if uddg:
                                url = unquote(uddg)
                            else:
                                continue
                        else:
                            url = raw_url

                        if not url or not url.startswith('http'):
                            continue

                        # Get title
                        title_texts = item.xpath('.//a[contains(@class, "result__a")]//text() | .//h2//text()')
                        title = ''.join(title_texts).strip() if title_texts else ''
                        if not title:
                            continue

                        # Get snippet
                        snippet_texts = item.xpath('.//*[contains(@class, "result__snippet")]//text()')
                        snippet = ''.join(snippet_texts).strip() if snippet_texts else title

                        result_type = 'video' if is_video_url(url) else 'website'
                        source = detect_platform(url)

                        results.append({
                            'url': url,
                            'title': title,
                            'description': snippet or title,
                            'thumbnail': favicon_url(url),
                            'duration': '' if result_type != 'video' else 'Unknown',
                            'source': source,
                            'platform': 'DuckDuckGo',
                            'type': result_type,
                        })

                        if socketio:
                            socketio.emit('new_result', {'result': results[-1]})

                    except Exception as e:
                        logger.error(f'Error processing DuckDuckGo result: {e}')

                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f'DuckDuckGo search error: {e}')
        return results

class DiscoveryAgent:
    """AI agent that discovers videos and feeds them into the ML database."""

    def __init__(self, database: MLDatabase):
        self.database = database
        self.scraper = VideoScraper()
        self.is_running = False
        # URLs added by the most recent discovery run, so a search can say how
        # many of them actually ended up among its own matches.
        self.last_added_urls = set()

    async def discover(self, query: str, socketio=None) -> int:
        """Discover videos for a query and add them to the database."""
        self.is_running = True
        try:
            results = await self.scraper.search_all(query, socketio)
            added = 0
            added_urls = set()
            for r in results:
                if self.database.add_video(
                    url=r['url'],
                    title=r['title'],
                    description=r.get('description', ''),
                    thumbnail=r.get('thumbnail', ''),
                    duration=r.get('duration', 'Unknown'),
                    source=r.get('source', 'Unknown'),
                    platform=r.get('platform', 'Unknown'),
                ):
                    added += 1
                    added_urls.add(r['url'])
            self.last_added_urls = added_urls
            # Skip expensive ML rebuild on Render (slow free tier CPU)
            if not os.environ.get('RENDER'):
                self.database.rebuild()
            logger.info(f"DiscoveryAgent: found {len(results)} videos, added {added} new to database")
            # Store results for direct return on Render
            self.last_results = results
            return added
        finally:
            self.is_running = False


class RankingAgent:
    """AI agent that ranks search results using ML + learned preferences."""

    def __init__(self, database: MLDatabase):
        self.database = database

    def rank(self, query: str, results: List[Dict]) -> List[Dict]:
        """Rank results by ML relevance score + click history."""
        if not results:
            return []

        # Get ML scores from database
        ml_results = self.database.search(query)
        ml_scores = {r['url']: r['score'] for r in ml_results}

        # Apply learned preferences (click boost)
        conn = connect_db(self.database.db_path)
        click_data = conn.execute(
            "SELECT clicked_url, COUNT(*) as clicks FROM learned_preferences GROUP BY clicked_url"
        ).fetchall()
        conn.close()
        click_boost = {row[0]: row[1] for row in click_data}

        # Combine scores
        for r in results:
            ml_score = ml_scores.get(r['url'], 0)
            clicks = click_boost.get(r['url'], 0)
            # Final score: ML relevance + click boost
            r['relevance_score'] = ml_score + (clicks * 0.1)

        # Sort by combined score
        results.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
        return results


# ============================================================================
# DOWNLOAD MANAGER
# ============================================================================

class DownloadManager:
    """Manages video downloads with yt-dlp and progress reporting."""

    def __init__(self):
        self.tokens = {}
        self.token_lock = threading.Lock()

    def _purge_stale_temp_dirs(self, max_age_seconds: int = 3600) -> None:
        """Delete download folders that were never served or never cleaned up."""
        root = tempfile.gettempdir()
        cutoff = time.time() - max_age_seconds
        try:
            names = os.listdir(root)
        except OSError:
            return
        for name in names:
            if not name.startswith('ytdl_'):
                continue
            path = os.path.join(root, name)
            try:
                if os.path.isdir(path) and os.path.getmtime(path) < cutoff:
                    shutil.rmtree(path, ignore_errors=True)
            except OSError:
                continue

    def resolve_url(self, url: str) -> str:
        """Resolve wrapper URLs to direct video URLs."""
        # Check if it's already a supported video URL
        for pattern in VIDEO_URL_PATTERNS:
            if re.match(pattern, url):
                return url
        return url

    def download(self, url: str, socketio, original_url: str = None) -> str:
        """Download a video and return a token for retrieval.

        Reports progress via Socket.IO when a socket is given; the HTTP
        endpoint passes None, so every emit has to be optional.
        """
        original_url = original_url or url
        url = self.resolve_url(url)

        def progress_hook(d):
            if not socketio:
                return
            if d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                downloaded = d.get('downloaded_bytes', 0)
                percent = (downloaded / total * 100) if total else 0
                speed = d.get('speed') or 0
                eta = d.get('eta') or 0
                socketio.emit('download_progress', {
                    'url': original_url,
                    'percent': round(percent, 1),
                    'downloaded': downloaded,
                    'total': total,
                    'speed': speed,
                    'eta': eta,
                })
            elif d['status'] == 'finished':
                socketio.emit('download_progress', {
                    'url': original_url,
                    'percent': 100,
                    'status': 'finished',
                })

        self._purge_stale_temp_dirs()
        tmp_dir = tempfile.mkdtemp(prefix='ytdl_')
        ydl_opts = {
            'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
            'merge_output_format': 'mp4',
            'ffmpeg_location': FFMPEG_PATH,
            'outtmpl': os.path.join(tmp_dir, '%(title).200s.%(ext)s'),
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'progress_hooks': [progress_hook],
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            downloaded_path = ydl.prepare_filename(info)
            if not os.path.exists(downloaded_path):
                base = os.path.splitext(downloaded_path)[0]
                downloaded_path = base + '.mp4'
            if not os.path.exists(downloaded_path):
                for fname in os.listdir(tmp_dir):
                    if fname.endswith(('.mp4', '.webm', '.mkv', '.m4a')):
                        downloaded_path = os.path.join(tmp_dir, fname)
                        break

            if not os.path.exists(downloaded_path):
                raise FileNotFoundError('Downloaded file not found')

            import uuid
            token = uuid.uuid4().hex
            with self.token_lock:
                self.tokens[token] = {
                    'path': downloaded_path,
                    'title': info.get('title', 'video'),
                    'tmp_dir': tmp_dir,
                }
            return token

    def get_file(self, token: str) -> Optional[Dict]:
        """Retrieve a downloaded file by token."""
        with self.token_lock:
            return self.tokens.pop(token, None)


# ============================================================================
# ROUTES SETUP
# ============================================================================

def setup_routes(app, socketio):
    """Set up Flask routes and Socket.IO event handlers for the AI search engine."""
    database = MLDatabase()

    # The genre model weighs phrases by how rare they are in this library, so it
    # has to read every document once. That fit takes seconds on a large index,
    # so it runs in the background: results get genre labels immediately and the
    # rarity weighting improves a moment later, without delaying startup.
    try:
        genre_model = MusicGenreModel()
        database.genre_model = genre_model

        def _fit_genres() -> None:
            started = time.time()
            try:
                genre_model.fit(list(database.documents))
                logger.info('Genre model fitted on %d videos in %.1fs',
                            genre_model.n_docs, time.time() - started)
            except Exception as fit_err:
                logger.warning('Genre model fit failed: %s', fit_err)

        threading.Thread(target=_fit_genres, daemon=True).start()
    except Exception as genre_err:
        logger.warning(f'Genre model unavailable: {genre_err}')

    scraper = VideoScraper()
    discovery_agent = DiscoveryAgent(database)
    ranking_agent = RankingAgent(database)
    download_manager = DownloadManager()
    # Timestamp of the running search (0 = idle). A timestamp rather than a flag
    # so a search that died without clearing it cannot block the app forever.
    search_started_at = 0.0

    # Background discovery runs from ONE worker so a burst of searches cannot
    # saturate the CPU with parallel scrapes and make the whole app unresponsive.
    discovery_queue = []
    discovery_lock = threading.Lock()
    discovery_worker = {'thread': None}

    # Incremented per search so a newer search can silence the one before it.
    search_state = {'token': 0}

    # Which results protocol each connected page speaks. Pages before batch
    # support get one event per result, so a cached page is never left blank.
    client_protocols = {}

    @socketio.on('client_protocol')
    def handle_client_protocol(data):
        try:
            client_protocols[request.sid] = int((data or {}).get('version') or 1)
        except (TypeError, ValueError):
            client_protocols[request.sid] = 1

    def _run_discovery(query: str, token: int) -> None:
        """Scrape for a query in the background and report what turned up."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                added = loop.run_until_complete(
                    asyncio.wait_for(
                        discovery_agent.discover(query, socketio=None),
                        timeout=DISCOVERY_TIMEOUT_DEFAULT,
                    )
                )
            finally:
                loop.close()
        except asyncio.TimeoutError:
            added = len(getattr(discovery_agent, 'last_added_urls', set()))
            logger.warning('Discovery timed out for %r; keeping what it stored', query)
        except Exception as exc:
            logger.error('Discovery failed for %r: %s', query, exc)
            return

        if token != search_state['token']:
            logger.info('Dropping discovery report for superseded search %r', query)
            return

        try:
            database.rebuild()
            new_urls = set(getattr(discovery_agent, 'last_added_urls', set()))
            new_matches = [r for r in database.search(query) if r['url'] in new_urls]
            if new_matches:
                new_matches = ranking_agent.rank(query, new_matches)
            socketio.emit('discovery_results', {
                'query': query,
                'discovered': added,
                'matched': len(new_matches),
                'total': database.count_matches(query),
                'stats': database.get_stats(),
                'results': new_matches,
            })
        except Exception as exc:
            logger.error('Discovery reporting failed for %r: %s', query, exc)

    def _discovery_worker_loop() -> None:
        while True:
            with discovery_lock:
                if not discovery_queue:
                    discovery_worker['thread'] = None
                    return
                query, token = discovery_queue.pop(0)
            _run_discovery(query, token)

    def start_background_discovery(query: str, token: int) -> None:
        with discovery_lock:
            if any(item[0] == query for item in discovery_queue):
                logger.info('Discovery already queued for %r', query)
                return
            discovery_queue.append((query, token))
            worker = discovery_worker.get('thread')
            if worker and worker.is_alive():
                return
            thread = threading.Thread(target=_discovery_worker_loop, daemon=True)
            discovery_worker['thread'] = thread
            thread.start()

    @socketio.on('connect')
    def handle_connect():
        logger.info('Client connected')
        stats = database.get_stats()
        socketio.emit('connected', {
            'status': 'AI Search Engine connected',
            'stats': stats,
        })

    @socketio.on('disconnect')
    def handle_disconnect():
        logger.info('Client disconnected')
        client_protocols.pop(request.sid, None)

    @socketio.on('search_query')
    def handle_search_query(data):
        """Handle a search query using the AI search engine."""
        nonlocal search_started_at
        query = (data or {}).get('query', '').strip()
        if not query:
            emit('search_error', {'error': 'No query provided'})
            return

        now = time.time()
        stale_after = DISCOVERY_TIMEOUT_DEFAULT + 60
        if search_started_at and now - search_started_at < stale_after:
            remaining = int(stale_after - (now - search_started_at))
            emit('search_error', {
                'error': f'A search is still running (about {remaining}s left). '
                         'Results already found stay on the page.'
            })
            return
        if search_started_at:
            logger.warning(
                'Previous search never cleared its lock after %.0fs; starting anyway',
                now - search_started_at,
            )

        search_started_at = now
        search_state['token'] += 1
        token = search_state['token']
        try:
            emit('search_started', {'query': query, 'token': token})
            is_render = os.environ.get('RENDER')

            if is_render:
                # FAST MODE on Render: skip ML, return scraper results directly
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    results = loop.run_until_complete(
                        discovery_agent.scraper.search_all(query, socketio)
                    )
                finally:
                    loop.close()

                # Stream results to frontend
                for r in results:
                    emit('new_result', {'result': r})

                # Add to database in background (no rebuild)
                added = 0
                for r in results:
                    if database.add_video(
                        url=r['url'], title=r['title'],
                        description=r.get('description', ''),
                        thumbnail=r.get('thumbnail', ''),
                        duration=r.get('duration', 'Unknown'),
                        source=r.get('source', 'Unknown'),
                        platform=r.get('platform', 'Unknown'),
                    ):
                        added += 1

                emit('search_completed', {
                    'query': query,
                    'total': len(results),
                    'discovered': added,
                    'stats': database.get_stats(),
                })
            else:
                # FULL MODE (local): answer from the index immediately. Scraping
                # is slow and used to hold the whole search hostage; it now runs
                # in the background and reports back when it finds something.
                ranked = ranking_agent.rank(query, database.search(query))

                # Send matches in batches. One event per result floods the socket
                # (hundreds of frames), and dropped frames looked like a cap.
                if client_protocols.get(request.sid, 1) >= 2:
                    batch_size = 200
                    for start in range(0, len(ranked), batch_size):
                        if token != search_state['token']:
                            logger.info('Search %r superseded; stopping its results', query)
                            return
                        emit('search_results', {
                            'query': query,
                            'token': token,
                            'results': ranked[start:start + batch_size],
                        })
                else:
                    # Older page: it only knows one-result-per-event.
                    for r in ranked:
                        if token != search_state['token']:
                            return
                        emit('new_result', {'result': r})

                total_matches = database.count_matches(query)

                log_search(database.db_path, query, len(ranked))

                emit('search_completed', {
                    'query': query,
                    'total': total_matches,
                    'shown': len(ranked),
                    'discovered': 0,
                    'discovered_matched': 0,
                    'discovering': True,
                    'stats': database.get_stats(),
                })

                start_background_discovery(query, token)
        except Exception as e:
            logger.error(f'Search error: {str(e)}')
            emit('search_error', {'error': str(e)})
        finally:
            search_started_at = 0.0

    @socketio.on('record_click')
    def handle_record_click(data):
        """Record a click so the ML can learn preferences."""
        url = (data or {}).get('url', '')
        title = (data or {}).get('title', '')
        query = (data or {}).get('query', '')
        if url and query:
            try:
                database.record_click(query, url, title)
            except sqlite3.Error as exc:
                # A click that cannot be stored must not break the page.
                logger.warning(f'Could not record click {url!r}: {exc}')

    @socketio.on('get_stats')
    def handle_get_stats():
        """Get database statistics."""
        emit('stats', database.get_stats())

    # --- Download routes ---

    @app.route('/download_file/<token>')
    def download_file(token):
        """Serve a previously downloaded file by token."""
        entry = download_manager.get_file(token)
        if not entry or not os.path.exists(entry['path']):
            return jsonify({'error': 'File not found or expired'}), 404

        safe_title = re.sub(r'[\\/:*?"<>|]', '_', entry.get('title', 'video'))
        filename = f'{safe_title}.mp4'
        file_path = entry['path']
        tmp_dir = entry.get('tmp_dir')

        logger.info(f'Serving file: {file_path} ({os.path.getsize(file_path)} bytes)')

        response = send_file(
            file_path,
            as_attachment=True,
            download_name=filename,
            mimetype='video/mp4',
        )

        @response.call_on_close
        def cleanup():
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                if tmp_dir and os.path.exists(tmp_dir):
                    shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception as e:
                logger.error(f'Cleanup error: {e}')

        return response

    @socketio.on('download_video')
    def handle_download_video(data):
        """Handle download requests with progress reporting."""
        url = (data or {}).get('url', '').strip()
        if not url:
            socketio.emit('download_error', {'url': '', 'error': 'No URL provided'})
            return

        logger.info(f'Download request: {url}')

        def run_download():
            try:
                token = download_manager.download(url, socketio, original_url=url)
                socketio.emit('download_complete', {
                    'url': url,
                    'token': token,
                    'title': 'video',
                })
            except yt_dlp.utils.DownloadError as e:
                err_msg = str(e)
                # Strip ANSI color codes
                err_msg = re.sub(r'\x1b\[[0-9;]*m', '', err_msg)
                if 'Sign in to confirm' in err_msg or 'cookies' in err_msg.lower():
                    err_msg = 'YouTube blocked this download (anti-bot protection). Downloads work best when running locally on your computer. On a cloud server, YouTube detects bot traffic.'
                elif 'Unsupported URL' in err_msg:
                    err_msg = 'This video source is not supported for download. YouTube and Dailymotion work best.'
                elif 'Unexpected response' in err_msg:
                    platform = detect_platform(url)
                    if platform == 'TikTok':
                        err_msg = 'TikTok blocks automated downloads. Try a YouTube or Dailymotion video instead.'
                    else:
                        err_msg = f'{platform} blocked the download. Try a different video.'
                elif 'impersonat' in err_msg.lower():
                    err_msg = 'This platform requires browser impersonation. YouTube videos work most reliably.'
                elif 'ffmpeg' in err_msg.lower():
                    err_msg = 'FFmpeg error: could not process video. Try a different format.'
                logger.error(f'Download error: {err_msg}')
                socketio.emit('download_error', {'url': url, 'error': err_msg})
            except Exception as e:
                err_msg = re.sub(r'\x1b\[[0-9;]*m', '', str(e))
                logger.error(f'Download error: {err_msg}')
                socketio.emit('download_error', {'url': url, 'error': err_msg})

        thread = threading.Thread(target=run_download, daemon=True)
        thread.start()

    # ========================================================================
    # HTTP API ENDPOINTS (for Vercel / no-WebSocket environments)
    # ========================================================================

    @app.route('/api/search', methods=['POST'])
    def api_search():
        """HTTP search endpoint - returns all results at once (no streaming)."""
        data = request.get_json(silent=True) or {}
        query = (data.get('query') or '').strip()
        if not query:
            return jsonify({'error': 'No query provided'}), 400

        try:
            is_render = os.environ.get('RENDER')

            if is_render:
                # FAST MODE: just scrape, no ML rebuild
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    results = loop.run_until_complete(
                        discovery_agent.scraper.search_all(query, socketio=None)
                    )
                finally:
                    loop.close()

                added = 0
                for r in results:
                    if database.add_video(
                        url=r['url'], title=r['title'],
                        description=r.get('description', ''),
                        thumbnail=r.get('thumbnail', ''),
                        duration=r.get('duration', 'Unknown'),
                        source=r.get('source', 'Unknown'),
                        platform=r.get('platform', 'Unknown'),
                    ):
                        added += 1

                return jsonify({
                    'query': query,
                    'total': len(results),
                    'discovered': added,
                    'results': results,
                    'stats': database.get_stats(),
                })
            else:
                # FULL MODE: ML search + discovery + ranking
                db_results = database.search(query)
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    discovered = loop.run_until_complete(
                        discovery_agent.discover(query, socketio=None)
                    )
                finally:
                    loop.close()

                database.rebuild()
                all_results = database.search(query)
                ranked = ranking_agent.rank(query, all_results)

                log_search(database.db_path, query, len(ranked))

                discovered_urls = getattr(discovery_agent, 'last_added_urls', set())
                return jsonify({
                    'query': query,
                    'total': database.count_matches(query),
                    'shown': len(ranked),
                    'discovered': discovered,
                    'discovered_matched': sum(1 for r in ranked if r['url'] in discovered_urls),
                    'results': ranked,
                    'stats': database.get_stats(),
                })
        except Exception as e:
            logger.error(f'API search error: {str(e)}')
            return jsonify({'error': str(e)}), 500

    @app.route('/api/stats', methods=['GET'])
    def api_stats():
        """Get database statistics."""
        return jsonify(database.get_stats())

    @app.route('/api/download', methods=['POST'])
    def api_download():
        """HTTP download endpoint - downloads video and returns token."""
        data = request.get_json(silent=True) or {}
        url = (data.get('url') or '').strip()
        if not url:
            return jsonify({'error': 'No URL provided'}), 400

        try:
            token = download_manager.download(url, socketio=None, original_url=url)
            return jsonify({
                'url': url,
                'token': token,
                'status': 'complete',
            })
        except yt_dlp.utils.DownloadError as e:
            err_msg = re.sub(r'\x1b\[[0-9;]*m', '', str(e))
            if 'Sign in to confirm' in err_msg or 'cookies' in err_msg.lower():
                err_msg = 'YouTube blocked this download (anti-bot protection). Downloads work best when running locally on your computer.'
            elif 'Unsupported URL' in err_msg:
                err_msg = 'This video source is not supported for download.'
            elif 'Unexpected response' in err_msg:
                platform = detect_platform(url)
                if platform == 'TikTok':
                    err_msg = 'TikTok blocks automated downloads. Try YouTube or Dailymotion.'
                else:
                    err_msg = f'{platform} blocked the download.'
            elif 'impersonat' in err_msg.lower():
                err_msg = 'This platform requires browser impersonation. YouTube works best.'
            return jsonify({'error': err_msg}), 400
        except Exception as e:
            err_msg = re.sub(r'\x1b\[[0-9;]*m', '', str(e))
            return jsonify({'error': err_msg}), 500

    logger.info("AI Search Engine routes configured")
