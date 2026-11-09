"""Downloader service for the deployed video search page.

The public site is served as static files from Cloudflare, which cannot run
yt-dlp. This is a small, separate Flask app that can: it downloads a video with
yt-dlp, reports progress, and hands the finished file back to the browser.

A download takes tens of seconds, longer than many hosts keep a request open,
so the API is asynchronous:

    POST /api/download          {url}  -> 202 {token, status: "queued"}
    GET  /api/download/<token>         -> {status, percent, speed, ...}
    GET  /download_file/<token>        -> the file, as an attachment
    GET  /health                       -> {ok: true}

Jobs and finished files live in memory and in the temp dir. That is deliberate:
one file, one reader, deleted as soon as it has been served.
"""

import hashlib
import os
import re
import subprocess
import shutil
import tempfile
import threading
import time
import uuid
from typing import Dict, Optional

from urllib.parse import quote, urljoin, urlparse

import requests
try:
    from curl_cffi import requests as cffi_requests
except ImportError:  # optional: the proxy still works for hosts that allow it
    cffi_requests = None
from flask import Flask, Response, jsonify, request, send_file, stream_with_context
from flask_cors import CORS
from imageio_ffmpeg import get_ffmpeg_exe
import yt_dlp

app = Flask(__name__)

# The search page runs on a different origin (Cloudflare, a LAN IP, a file
# server), so every route has to answer cross-origin requests.
CORS(app, resources={r"/*": {
    "origins": "*",
    "methods": ["GET", "POST", "OPTIONS"],
    "allow_headers": ["Content-Type"],
    "expose_headers": ["Content-Disposition"],
    "max_age": 86400,
}})

# Hosted hardware is small and the network is metered, so the default cap is
# 720p. The local app still downloads 1080p because it runs on the user's PC.
MAX_HEIGHT = int(os.environ.get('MAX_HEIGHT', '720'))

# Finished downloads are kept this long so a slow poll cannot miss the file.
JOB_TTL_SECONDS = int(os.environ.get('JOB_TTL_SECONDS', '3600'))

# A public download endpoint is worth protecting: cap how much work it can be
# made to do at once.
MAX_ACTIVE_JOBS = int(os.environ.get('MAX_ACTIVE_JOBS', '3'))
MAX_JOBS_PER_IP = int(os.environ.get('MAX_JOBS_PER_IP', '2'))

# YouTube refuses datacenter IPs more often than home connections. Pointing this
# at a cookies file exported from a browser is the usual workaround; the file is
# never shipped with the service.
COOKIES_FILE = os.environ.get('YT_COOKIES_FILE', '')
# Hosted platforms give you environment variables, not a file picker, so the
# cookie jar can also arrive as text. Both end up as one netscape-format file
# that yt-dlp is pointed at.
COOKIES_TEXT = os.environ.get('YT_COOKIES', '')


def _cookie_path() -> str:
    """The cookie file yt-dlp should use, or an empty string when there is none."""
    if COOKIES_FILE and os.path.exists(COOKIES_FILE):
        return COOKIES_FILE
    if not COOKIES_TEXT.strip():
        return ''
    path = os.path.join(tempfile.gettempdir(), 'yt_cookies.txt')
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        body = COOKIES_TEXT.strip()
        if not body.startswith('# HTTP Cookie File'):
            body = '# HTTP Cookie File\n' + body
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(body + '\n')
    return path

_jobs: Dict[str, dict] = {}
_jobs_lock = threading.Lock()
_active_jobs = 0
_active_lock = threading.Lock()


def _purge_expired() -> None:
    """Drop jobs whose time is up, and the files they still hold."""
    cutoff = time.time() - JOB_TTL_SECONDS
    with _jobs_lock:
        expired = [t for t, job in _jobs.items() if job['created'] < cutoff]
        jobs = [_jobs.pop(t) for t in expired]
    for job in jobs:
        _delete_files(job)


def _delete_files(job: dict) -> None:
    path = job.get('path')
    tmp_dir = job.get('tmp_dir')
    try:
        if path and os.path.exists(path):
            os.remove(path)
        if tmp_dir and os.path.isdir(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except OSError:
        pass


def _set(token: str, **fields) -> None:
    with _jobs_lock:
        job = _jobs.get(token)
        if job is not None:
            job.update(fields)


def _is_supported_url(url: str) -> bool:
    return bool(re.match(r'^https?://[^\s/]+', url))


# yt-dlp can imitate a real browser's TLS fingerprint when curl_cffi is
# installed, which is the difference between YouTube serving the video and
# answering "requires impersonation". The desktop app bundles it for the same
# reason; here it is optional so the image still runs without it.
try:
    import curl_cffi  # noqa: F401
    from yt_dlp.networking.impersonate import ImpersonateTarget
    # yt-dlp asserts on a plain string here and the download dies with an empty
    # AssertionError, so the target is parsed into the object it expects.
    IMPERSONATE = ImpersonateTarget.from_str(os.environ.get('YT_IMPERSONATE', 'chrome'))
except ImportError:
    IMPERSONATE = None


def _run_download(token: str, url: str) -> None:
    """Download one video, keeping the job entry up to date as it goes."""
    global _active_jobs
    tmp_dir = tempfile.mkdtemp(prefix='ytdl_')

    def progress_hook(d):
        status = d.get('status')
        if status == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            percent = (downloaded / total * 100) if total else 0
            _set(token,
                 status='downloading',
                 percent=round(percent, 1),
                 downloaded=downloaded,
                 total=total,
                 speed=d.get('speed') or 0,
                 eta=d.get('eta') or 0)
        elif status == 'finished':
            _set(token, status='processing', percent=100)

    ydl_opts = {
        'format': (f'bestvideo[height<={MAX_HEIGHT}][ext=mp4]+bestaudio[ext=m4a]/'
                   f'bestvideo[height<={MAX_HEIGHT}]+bestaudio/'
                   f'best[height<={MAX_HEIGHT}]/best'),
        'merge_output_format': 'mp4',
        'ffmpeg_location': get_ffmpeg_exe(),
        'outtmpl': os.path.join(tmp_dir, '%(title).200s.%(ext)s'),
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'progress_hooks': [progress_hook],
        # A stalled host should fail the job instead of hanging forever.
        'socket_timeout': 30,
    }
    jar = _cookie_path()
    if jar:
        ydl_opts['cookiefile'] = jar
    if IMPERSONATE:
        ydl_opts['impersonate'] = IMPERSONATE

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title') or 'video'
            path = ydl.prepare_filename(info)
            if not os.path.exists(path):
                path = os.path.splitext(path)[0] + '.mp4'
            if not os.path.exists(path):
                for name in os.listdir(tmp_dir):
                    if name.endswith(('.mp4', '.webm', '.mkv', '.m4a')):
                        path = os.path.join(tmp_dir, name)
                        break
        if not os.path.exists(path):
            raise FileNotFoundError('Downloaded file not found')

        _set(token, status='complete', percent=100, title=title,
             path=path, tmp_dir=tmp_dir)
    except yt_dlp.utils.DownloadError as exc:
        _set(token, status='error', error=_friendly_error(str(exc), url),
             tmp_dir=tmp_dir)
    except Exception as exc:  # noqa: BLE001 - surfaced to the page as text
        _set(token, status='error', error=_clean(str(exc)), tmp_dir=tmp_dir)
    finally:
        with _active_lock:
            _active_jobs -= 1


def _clean(message: str) -> str:
    """yt-dlp colourises its errors, which look broken in a toast."""
    return re.sub(r'\x1b\[[0-9;]*m', '', message).strip()


def _friendly_error(message: str, url: str) -> str:
    text = _clean(message)
    lowered = text.lower()
    if 'sign in to confirm' in lowered or 'cookies' in lowered:
        return ('The host was refused by the source (anti-bot check). '
                'This usually means the video site blocks cloud servers; '
                'the same download works from the app on your own computer.')
    if 'unsupported url' in lowered:
        return 'This source does not support downloading. YouTube and Dailymotion work best.'
    if 'impersonat' in lowered:
        return ('This source needs a browser-like connection and impersonation '
                'failed. Install curl_cffi (it is in requirements.txt) or set '
                'YT_IMPERSONATE to a target this machine supports.')
    if 'private video' in lowered or 'unavailable' in lowered:
        return 'This video is private or unavailable.'
    if 'ffmpeg' in lowered:
        return 'FFmpeg could not process this video. Try a different one.'
    if 'timed out' in lowered or 'timeout' in lowered:
        return 'The source took too long to respond.'
    # Keep the message readable: yt-dlp prefixes it with "ERROR: ".
    return text.replace('ERROR: ', '')[:300]


@app.route('/health')
def health():
    # A hosted deploy is checked from the outside, so this says enough to tell a
    # working service from one that is awake but has no cookie jar.
    with _jobs_lock:
        active = len([job for job in _jobs.values()
                      if job.get('status') in ('queued', 'downloading', 'processing')])
    return jsonify({
        'ok': True,
        'max_height': MAX_HEIGHT,
        'cookies': bool(_cookie_path()),
        'active_jobs': active,
    })


@app.route('/api/discover', methods=['POST', 'OPTIONS'])
def api_discover():
    """Find videos for a search term, without downloading any of them.

    The deployed page cannot search YouTube itself: a Worker runs on a datacenter
    address that YouTube refuses, and the public mirrors (Invidious, Piped) answer
    403 from there as well. This machine can, because yt-dlp here looks like a
    browser on a home connection. So the page asks this service for the list and
    sends what it finds to the site's database.

    extract_flat means yt-dlp reads the search page only: no per-video requests,
    no media, about a second for twenty results.
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    data = request.get_json(silent=True) or {}
    query = (data.get('query') or '').strip()[:120]
    if not query:
        return jsonify({'error': 'No search term given'}), 400
    try:
        limit = int(data.get('limit') or 20)
    except (TypeError, ValueError):
        limit = 20
    # More than one page's worth, so a repeat search can show different videos
    # instead of the same twenty.
    limit = max(1, min(50, limit))

    options = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extract_flat': True,
        'socket_timeout': 20,
        'extractor_args': {'youtube': {'skip': ['dash', 'hls']}},
    }
    cookies = _cookie_path()
    if cookies:
        options['cookiefile'] = cookies

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info('ytsearch%d:%s' % (limit, query), download=False)
    except Exception as exc:  # noqa: BLE001 - reported to the page as text
        return jsonify({'error': _friendly_error(str(exc), query)}), 502

    videos = _video_entries(info)
    return jsonify({'query': query, 'count': len(videos), 'videos': videos})


def _video_entries(info) -> list:
    """Turns yt-dlp's listing entries into the shape the page's cards read."""
    videos = []
    for entry in (info or {}).get('entries') or []:
        if not entry:
            continue
        link = entry.get('webpage_url') or entry.get('url') or ''
        title = (entry.get('title') or '').strip()
        if not link.startswith('http') or not title:
            continue
        videos.append({
            'url': link,
            'title': title[:300],
            'description': (entry.get('description') or '')[:500],
            'thumbnail': _best_thumbnail(entry),
            'duration': _clock(entry.get('duration')),
            'source': entry.get('ie_key') or 'YouTube',
        })
    return videos


@app.route('/api/top', methods=['POST', 'OPTIONS'])
def api_top():
    """The most-viewed videos for a search, or the contents of a playlist.

    YouTube's results page takes a filter for "sort by view count", and yt-dlp
    reads that listing without needing a key. That is what a "top 100" means
    here: the hundred most watched videos for the words, in that order. A
    playlist URL is read the same way, which covers any list someone has made.
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    data = request.get_json(silent=True) or {}
    query = (data.get('query') or '').strip()[:120]
    playlist = (data.get('url') or '').strip()
    try:
        limit = int(data.get('limit') or 100)
    except (TypeError, ValueError):
        limit = 100
    limit = max(1, min(100, limit))

    if playlist.startswith('http'):
        target = playlist
    elif query:
        # sp=CAMSAhAB is YouTube's own "sort by view count" filter.
        target = ('https://www.youtube.com/results?search_query=%s&sp=CAMSAhAB'
                  % quote(query))
    else:
        return jsonify({'error': 'No search term or playlist was given'}), 400

    options = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extract_flat': True,
        'playlistend': limit,
        'socket_timeout': 30,
    }
    cookies = _cookie_path()
    if cookies:
        options['cookiefile'] = cookies

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(target, download=False)
    except Exception as exc:  # noqa: BLE001 - reported to the page as text
        return jsonify({'error': _friendly_error(str(exc), target)}), 502

    videos = _video_entries(info)
    return jsonify({
        'query': query,
        'count': len(videos),
        'title': (info or {}).get('title') or query,
        'videos': videos[:limit],
    })


def _best_thumbnail(entry: Dict) -> str:
    thumbnails = entry.get('thumbnails') or []
    if thumbnails:
        # The list runs smallest to largest, so the last one is the readable one.
        return str(thumbnails[-1].get('url') or '')
    return str(entry.get('thumbnail') or '')


def _clock(seconds) -> str:
    try:
        total = int(seconds or 0)
    except (TypeError, ValueError):
        return 'Unknown'
    if total <= 0:
        return 'Unknown'
    return '%d:%02d' % (total // 60, total % 60)


# Files prepared for the in-page player, keyed by watch URL. A handful is enough:
# the page plays one video at a time and a re-open should not download it twice.
PLAY_CACHE = {}
PLAY_MAX_FILES = 3
PLAY_TTL_SECONDS = 900


def _download_to(target: str, tmp_dir: str):
    """Fetches one target into tmp_dir and returns the files it produced."""
    options = {
        'quiet': True,
        'no_warnings': True,
        # A playlist link is played as its first video rather than refused: the
        # card exists to be watched, and a list has a first thing in it.
        'playlist_items': '1',
        'socket_timeout': 30,
        # A preview for the player, not an archive copy: 480p starts far sooner.
        # No container is demanded here: the result is remuxed into mp4 below, and
        # asking for one made some videos fail as "format not available".
        'format': 'best[height<=480]/best/worst',
        'outtmpl': os.path.join(tmp_dir, 'video.%(ext)s'),
        'ffmpeg_location': os.path.dirname(get_ffmpeg_exe()),
    }
    cookies = _cookie_path()
    if cookies:
        options['cookiefile'] = cookies

    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.extract_info(target, download=True)

    files = [os.path.join(tmp_dir, name) for name in os.listdir(tmp_dir)]
    files = [path for path in files if os.path.isfile(path) and os.path.getsize(path) > 0]
    if not files:
        raise RuntimeError('nothing was downloaded for that link')
    return files


def _spotify_title(url: str) -> str:
    try:
        response = requests.get('https://open.spotify.com/oembed', params={'url': url},
                                timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        if response.ok:
            return (response.json().get('title') or '').strip()[:120]
    except Exception:
        pass
    return ''


def _page_search_term(url: str) -> str:
    """The page's own title, which is what gets searched for as a last resort."""
    try:
        response = requests.get(url, timeout=20, headers={
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                           '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')})
        match = re.search(r'<title[^>]*>(.*?)</title>', response.text, re.I | re.S)
        if not match:
            return ''
        title = re.sub(r'\s+', ' ', match.group(1)).strip()
        for suffix in (' - Spotify', ' | Spotify', ' - YouTube', ' - Dailymotion',
                       ' - TikTok', ' | Facebook'):
            title = title.replace(suffix, '')
        return title[:120]
    except Exception:
        return ''


@app.route('/api/play')
def api_play():
    """The video itself, for a host whose CDN will not stream to the browser.

    Neither TikTok's signed file URL nor Dailymotion's HLS playlist can be fetched
    straight from the page: one is refused by the browser's opaque-response guard,
    the other has no CORS headers, and the signed URL is refused even from here
    when it is fetched cold. yt-dlp can download both, so the file is fetched once,
    kept briefly, and served from this machine - a same-machine video element is
    always allowed.
    """
    url = request.args.get('url', '').strip()
    if not re.match(r'^https?://', url):
        return jsonify({'error': 'That is not a video link'}), 400

    key = hashlib.sha1(url.encode('utf-8')).hexdigest()
    cached = PLAY_CACHE.get(key)
    if cached and os.path.exists(cached['path']) and time.time() - cached['at'] < PLAY_TTL_SECONDS:
        return send_file(cached['path'], conditional=True)

    if cached:
        PLAY_CACHE.pop(key, None)
        shutil.rmtree(os.path.dirname(cached['path']), ignore_errors=True)

    tmp_dir = tempfile.mkdtemp(prefix='play_')

    # Some links are not videos at all. Spotify is the common one: it is DRM and
    # cannot be downloaded, but its own oEmbed answers with the real title, and
    # that title finds the same song on YouTube. So every link gets a chance, and
    # a link that refuses to be extracted is searched for by name instead of
    # leaving the person with nothing to play.
    attempts = [url]
    if 'spotify.com' in urlparse(url).netloc.lower():
        term = _spotify_title(url)
        attempts = ['ytsearch1:%s' % term] if term else []

    files = None
    last_error = ''
    for attempt in attempts:
        try:
            files = _download_to(attempt, tmp_dir)
            break
        except Exception as exc:  # noqa: BLE001 - reported to the page as text
            last_error = str(exc)

    if files is None and 'spotify.com' not in urlparse(url).netloc.lower():
        term = _page_search_term(url)
        if term:
            try:
                files = _download_to('ytsearch1:%s' % term, tmp_dir)
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)

    if files is None:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return jsonify({'error': _friendly_error(last_error, url)}), 502

    files = [os.path.join(tmp_dir, name) for name in os.listdir(tmp_dir)]
    files = [path for path in files if os.path.isfile(path) and os.path.getsize(path) > 0]
    if not files:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return jsonify({'error': 'Nothing was downloaded for that video.'}), 404

    # What yt-dlp saves for an HLS source is not always a container a browser
    # will open: Chrome answers DEMUXER_ERROR_COULD_NOT_OPEN. A stream-copy remux
    # into a normal, faststart mp4 fixes that and costs a few seconds.
    remuxed = os.path.join(tmp_dir, 'play.mp4')
    try:
        ffmpeg = get_ffmpeg_exe()
        completed = subprocess.run(
            [ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-i', files[0],
             '-c', 'copy', '-movflags', '+faststart', remuxed],
            capture_output=True, timeout=300)
        if completed.returncode == 0 and os.path.getsize(remuxed) > 0:
            files = [remuxed]
    except Exception:
        # A remux that fails must not lose an otherwise usable download.
        pass

    while len(PLAY_CACHE) >= PLAY_MAX_FILES:
        oldest_key = next(iter(PLAY_CACHE))
        oldest = PLAY_CACHE.pop(oldest_key)
        shutil.rmtree(os.path.dirname(oldest['path']), ignore_errors=True)

    PLAY_CACHE[key] = {'path': files[0], 'at': time.time()}
    return send_file(files[0], conditional=True)


@app.route('/api/stream')
def api_stream():
    """Hands the browser a video file from an origin that refuses it.

    TikTok's CDN and Dailymotion's CDN both refuse a direct request from the page
    (Chrome blocks the first with ORB, the second has no CORS at all), but a video
    element pointed at this service is same-machine and allowed. Range headers are
    passed through so seeking works, and an HLS playlist is rewritten so its
    segments come back through here as well.
    """
    target = request.args.get('url', '').strip()
    if not re.match(r'^https?://', target):
        return jsonify({'error': 'That is not a media link'}), 400

    # The CDNs check where the request appears to come from, and refuse a bare
    # client with 403 even for a signed URL. These are the same headers yt-dlp
    # sends when it reads the page.
    host = urlparse(target).netloc.lower()
    referer = 'https://www.tiktok.com/'
    if 'dailymotion' in host or 'dmcdn' in host:
        referer = 'https://www.dailymotion.com/'
    elif 'youtube' in host or 'googlevideo' in host:
        referer = 'https://www.youtube.com/'
    headers = {
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'),
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': referer,
        'Origin': referer.rstrip('/'),
    }
    if request.headers.get('Range'):
        headers['Range'] = request.headers['Range']

    # TikTok's CDN answers a plain client with 403 even for a signed URL: it
    # fingerprints the TLS handshake. curl_cffi is already here for yt-dlp, and it
    # is what makes the request look like the Chrome the link was made for.
    if cffi_requests is not None:
        upstream = cffi_requests.get(target, headers=headers, stream=True, timeout=40,
                                     impersonate='chrome')
    else:
        upstream = requests.get(target, headers=headers, stream=True, timeout=40)

    if '.m3u8' in target or 'mpegurl' in (upstream.headers.get('Content-Type') or ''):
        body = upstream.text
        base = target.rsplit('/', 1)[0] + '/'
        proxy = request.host_url.rstrip('/') + '/api/stream?url='
        out = []
        for line in body.splitlines():
            text = line.strip()
            if not text:
                continue
            if text.startswith('#'):
                # Key and init-segment URIs live inside tags.
                out.append(re.sub(
                    r'URI="([^"]+)"',
                    lambda m: 'URI="%s%s"' % (proxy, quote(urljoin(base, m.group(1)), safe='')),
                    text))
            else:
                out.append(proxy + quote(urljoin(base, text), safe=''))
        response = Response('\n'.join(out), status=200)
        response.headers['Content-Type'] = 'application/vnd.apple.mpegurl'
        return response

    def relay():
        for chunk in upstream.iter_content(chunk_size=65536):
            if chunk:
                yield chunk

    response = Response(stream_with_context(relay()), status=upstream.status_code)
    for header in ('Content-Type', 'Content-Length', 'Content-Range', 'Accept-Ranges', 'ETag'):
        if upstream.headers.get(header):
            response.headers[header] = upstream.headers[header]
    if 'Content-Type' not in response.headers:
        response.headers['Content-Type'] = 'video/mp4'
    response.headers['Accept-Ranges'] = response.headers.get('Accept-Ranges', 'bytes')
    return response


@app.route('/api/resolve', methods=['POST', 'OPTIONS'])
def api_resolve():
    """A direct stream URL for a video the page cannot embed.

    Dailymotion answers its embed endpoint with "Forbidden" from this site and
    TikTok's embed is black for most clips, so neither can be framed. yt-dlp here
    can still read the media URL behind the watch page, and the browser plays it
    directly - an mp4 as it is, an HLS playlist through hls.js.
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    data = request.get_json(silent=True) or {}
    url = (data.get('url') or '').strip()
    if not url or not _is_supported_url(url):
        return jsonify({'error': 'That is not a video link'}), 400

    options = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'noplaylist': True,
        'socket_timeout': 25,
        'format': 'best[ext=mp4]/best',
    }
    cookies = _cookie_path()
    if cookies:
        options['cookiefile'] = cookies

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False) or {}
    except Exception as exc:  # noqa: BLE001 - reported to the page as text
        return jsonify({'error': _friendly_error(str(exc), url)}), 502

    stream = str(info.get('url') or '')
    if not stream:
        requested = info.get('requested_formats') or []
        if requested:
            stream = str(requested[0].get('url') or '')
    if not stream:
        return jsonify({'error': 'No playable stream was found for that video.'}), 404

    return jsonify({
        'stream': stream,
        'kind': 'hls' if '.m3u8' in stream else 'file',
        'title': info.get('title') or '',
        'duration': _clock(info.get('duration')),
    })


@app.route('/api/download', methods=['POST', 'OPTIONS'])
def api_download():
    if request.method == 'OPTIONS':
        return ('', 204)

    _purge_expired()

    data = request.get_json(silent=True) or {}
    url = (data.get('url') or '').strip()
    if not url:
        return jsonify({'error': 'No URL provided'}), 400
    if not _is_supported_url(url):
        return jsonify({'error': 'That is not a video link'}), 400

    ip = (request.headers.get('X-Forwarded-For') or request.remote_addr or '').split(',')[0].strip()
    global _active_jobs
    with _active_lock:
        if _active_jobs >= MAX_ACTIVE_JOBS:
            return jsonify({'error': 'The downloader is busy. Try again in a minute.'}), 429
        mine = sum(1 for job in _jobs.values() if job.get('ip') == ip and job['status'] in ('queued', 'downloading', 'processing'))
        if mine >= MAX_JOBS_PER_IP:
            return jsonify({'error': 'You already have downloads running.'}), 429
        _active_jobs += 1

    token = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[token] = {
            'status': 'queued',
            'percent': 0,
            'title': '',
            'error': '',
            'path': None,
            'tmp_dir': None,
            'url': url,
            'ip': ip,
            'created': time.time(),
        }

    threading.Thread(target=_run_download, args=(token, url), daemon=True).start()
    return jsonify({'token': token, 'status': 'queued', 'url': url}), 202


@app.route('/api/download/<token>')
def api_download_status(token):
    with _jobs_lock:
        job = _jobs.get(token)
        if job is None:
            return jsonify({'error': 'Unknown or expired download'}), 404
        payload = {
            'status': job['status'],
            'percent': job['percent'],
            'downloaded': job.get('downloaded', 0),
            'total': job.get('total', 0),
            'speed': job.get('speed', 0),
            'eta': job.get('eta', 0),
            'title': job['title'],
            'error': job['error'],
        }
    return jsonify(payload)


@app.route('/download_file/<token>')
def download_file(token):
    with _jobs_lock:
        job = _jobs.get(token)
        if job is None or job['status'] != 'complete':
            return jsonify({'error': 'File not found or expired'}), 404
        path = job['path']
        title = job['title']

    if not path or not os.path.exists(path):
        return jsonify({'error': 'File not found or expired'}), 404

    safe_title = re.sub(r'[\\/:*?"<>|]', '_', title or 'video')[:120]
    response = send_file(path, as_attachment=True,
                         download_name=f'{safe_title}.mp4', mimetype='video/mp4')

    @response.call_on_close
    def cleanup():
        # One download, one reader: the file has no further use.
        with _jobs_lock:
            finished = _jobs.pop(token, None)
        if finished:
            _delete_files(finished)

    return response


if __name__ == '__main__':
    # Local runs use the Flask dev server; the container uses gunicorn.
    port = int(os.environ.get('PORT', '8080'))
    app.run(host='0.0.0.0', port=port, threaded=True)
