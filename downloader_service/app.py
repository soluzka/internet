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

import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from typing import Dict, Optional

from flask import Flask, jsonify, request, send_file
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
