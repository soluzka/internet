import os
import sys
import tempfile

import yt_dlp
from imageio_ffmpeg import get_ffmpeg_exe

try:
    import curl_cffi
    print('curl_cffi', curl_cffi.__version__)
except Exception as exc:  # noqa: BLE001
    print('no curl_cffi:', exc)

tmp = tempfile.mkdtemp(prefix='probe_')
opts = {
    'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]/best',
    'merge_output_format': 'mp4',
    'ffmpeg_location': get_ffmpeg_exe(),
    'outtmpl': os.path.join(tmp, '%(title).200s.%(ext)s'),
    'noplaylist': True,
    'quiet': False,
    'no_warnings': False,
    'socket_timeout': 30,
    'impersonate': 'chrome',
}
url = sys.argv[1] if len(sys.argv) > 1 else 'https://www.youtube.com/watch?v=jNQXAC9IVRw'
try:
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        print('OK', info.get('title'), ydl.prepare_filename(info))
except Exception as exc:  # noqa: BLE001
    print('TYPE', type(exc).__name__)
    print('REPR', repr(exc))
    print('STR', str(exc))
