import os
import sys
import time
import shutil
import logging
import threading
import subprocess
import tempfile

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Add the scrape directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
scrape_dir = os.path.join(current_dir, 'scrape')
sys.path.insert(0, current_dir)
sys.path.insert(0, scrape_dir)

from flask import Flask, send_from_directory, send_file, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO
from ai_engine import setup_routes

# When frozen by PyInstaller, the path to the resources is different
if getattr(sys, 'frozen', False):
    base_dir = sys._MEIPASS
    logger.info(f"Running in PyInstaller bundle. Base dir: {base_dir}")
else:
    base_dir = current_dir
    logger.info(f"Running in development mode. Base dir: {base_dir}")

# Resolve static folder - try multiple locations for Vercel compatibility
static_folder = None
_candidate_paths = [
    os.path.join(base_dir, 'public'),                                          # next to app.py
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'public'),        # relative to module
    os.path.join(os.getcwd(), 'public'),                                        # current working dir
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'public'),  # one level up
    '/var/task/public',                                                         # Vercel serverless
    '/var/task/scrape_videos/public',                                           # Vercel with package
]
for _p in _candidate_paths:
    if os.path.exists(_p) and os.path.isdir(_p):
        static_folder = _p
        break
if not static_folder:
    # Last resort: use the first candidate even if it doesn't exist yet
    static_folder = os.path.join(base_dir, 'public')
logger.info(f"Static folder path: {static_folder}")
logger.info(f"Static folder exists: {os.path.exists(static_folder)}")
if os.path.exists(static_folder):
    logger.info(f"Static folder contents: {os.listdir(static_folder)}")

app = Flask(__name__, 
           static_folder=static_folder,
           static_url_path='')

# Configure CORS
CORS(app, resources={
    r"/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"],
        "supports_credentials": True
    }
})

# Initialize SocketIO - use eventlet on Render, threading locally
async_mode = 'eventlet' if os.environ.get('RENDER') else 'threading'
try:
    import eventlet
    eventlet.monkey_patch()
except ImportError:
    async_mode = 'threading'

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode=async_mode,
    logger=False,
    engineio_logger=False
)

# --- Voice search ---------------------------------------------------------
# Transcribes a recorded clip with the speech recogniser built into Windows,
# so voice search needs no API key and no network round trip.
SAPI_SCRIPT = r'''
Add-Type -AssemblyName System.Speech
$rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine
$rec.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))
$rec.SetInputToWaveFile('%s')
$result = $rec.Recognize()
if ($result) {
    [Console]::Out.WriteLine($result.Text)
    [Console]::Out.Write($result.Confidence)
}
$rec.Dispose()
'''

# Anything below this is usually background noise, not a spoken query.
MIN_CONFIDENCE = 0.3

# Whisper is the primary engine; the Windows recogniser is the fallback.
WHISPER_MODEL = os.environ.get('WHISPER_MODEL', 'base.en')
_whisper_model = None
_whisper_unavailable = False


def _transcribe_with_whisper(wav_path):
    """Return the transcript, or None when Whisper is not usable here."""
    global _whisper_model, _whisper_unavailable
    if _whisper_unavailable:
        return None
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        logger.warning('faster-whisper is not installed; using the Windows recogniser')
        _whisper_unavailable = True
        return None

    if _whisper_model is None:
        source = WHISPER_MODEL
        # The build ships the weights, so a frozen app needs no download.
        bundled = os.path.join(base_dir, 'whisper', 'base.en')
        if os.path.isdir(bundled):
            source = bundled
        logger.info(f'Loading Whisper model {source}')
        _whisper_model = WhisperModel(source, device='cpu', compute_type='int8')

    # The VAD is a data file beside the package, not an import, so a build can
    # miss it and kill Whisper outright. Transcribe without it instead.
    for vad in (True, False):
        try:
            segments, _info = _whisper_model.transcribe(
                wav_path, beam_size=1, language='en', vad_filter=vad)
            return ' '.join(segment.text.strip() for segment in segments).strip()
        except Exception:
            if not vad:
                raise
            logger.warning('Whisper VAD unavailable; transcribing without it')


def _audio_to_wav(audio_bytes, suffix):
    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    src = tempfile.NamedTemporaryFile(delete=False, suffix=suffix).name
    dst = src + '.wav'
    with open(src, 'wb') as handle:
        handle.write(audio_bytes)
    try:
        proc = subprocess.run(
            [ffmpeg, '-y', '-hide_banner', '-loglevel', 'error', '-i', src,
             '-ac', '1', '-ar', '16000', '-f', 'wav', dst],
            capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or 'ffmpeg could not decode the clip')
        return dst
    finally:
        try:
            os.remove(src)
        except OSError:
            pass


def _recognize_wav(wav_path):
    script = SAPI_SCRIPT % wav_path.replace("'", "''")
    proc = subprocess.run(
        ['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
        capture_output=True, text=True, timeout=90)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or 'speech recognition failed')

    lines = [line.strip() for line in proc.stdout.strip().splitlines() if line.strip()]
    if len(lines) < 2:
        return ''
    text, confidence = lines[0], lines[-1]
    try:
        if float(confidence) < MIN_CONFIDENCE:
            logger.info(f"Discarding low-confidence transcript ({confidence}): {text}")
            return ''
    except ValueError:
        pass
    return text


# ---------------------------------------------------------------------------
# The local AI: forwarded to song_service/app.py on this machine.
#
# The page asks its own origin first, so these routes must exist here - without
# them a POST fell through to the static catch-all and came back 405, and the
# page quietly used the instrument-only fallback instead of the real model.
# Forwarding keeps the page same-origin, so there is no CORS or preflight.
# ---------------------------------------------------------------------------
SONG_SERVICE = os.environ.get('SONG_SERVICE_URL', 'http://127.0.0.1:8090').rstrip('/')
SONG_TIMEOUT = float(os.environ.get('SONG_PROXY_TIMEOUT', '1800'))

# The weights are ~10 GB of CUDA tensors: they cannot travel inside a one-file
# EXE, and copying them per launch would cost minutes. What the EXE can do is
# look for the song_service folder beside itself (or one level up, when it sits
# in dist\) and start it, so the AI it sings with is the one installed next to
# the executable rather than wherever the process happened to be started from.
_exe_dir = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, 'frozen', False) else current_dir
_song_service_proc = None
_song_service_lock = threading.Lock()


# The source of the service, small enough (~120 KB) to ride inside the exe. With
# these files the app can set the AI up in any folder, instead of only being able
# to use a song_service someone had already installed by hand.
_SERVICE_SOURCE = ('app.py', 'lyrics.py', 'install.py', 'models.json')


def _seed_song_service(target):
    """Write the bundled service source into target; return it if it worked."""
    bundled = os.path.join(getattr(sys, '_MEIPASS', ''), 'song_service')
    if not os.path.isdir(bundled):
        return None
    try:
        os.makedirs(target, exist_ok=True)
        for name in _SERVICE_SOURCE:
            source = os.path.join(bundled, name)
            if os.path.exists(source):
                shutil.copy2(source, os.path.join(target, name))
    except OSError:
        logger.exception('could not write the service into %s', target)
        return None
    return target if os.path.exists(os.path.join(target, 'app.py')) else None


def _song_service_dirs():
    """Candidate song_service folders: beside the exe first, then one level up.

    If neither exists, the bundled source is unpacked beside the exe, so the app
    can create and fill that folder on its own rather than refusing to sing.
    """
    roots = [_exe_dir, os.path.dirname(_exe_dir)]
    seen = set()
    folders = []
    for root in roots:
        folder = os.path.join(root, 'song_service')
        key = os.path.normcase(os.path.abspath(folder))
        if root and key not in seen and os.path.isdir(folder):
            seen.add(key)
            folders.append(folder)
    if not folders:
        seeded = _seed_song_service(os.path.join(_exe_dir, 'song_service'))
        if seeded:
            logger.info('Unpacked the song service into %s', seeded)
            folders.append(seeded)
    return folders


def _song_service_up(timeout=2.0):
    import urllib.request

    try:
        with urllib.request.urlopen(SONG_SERVICE + '/health', timeout=timeout) as answer:
            return answer.status == 200
    except Exception:  # noqa: BLE001 - a closed port is the normal "not started" case
        return False


_ai_install_proc = None


def _ai_missing(folder):
    """What the AI is missing in this folder, as short labels; empty if ready."""
    python = os.path.join(folder, '.venv', 'Scripts', 'python.exe')
    install = os.path.join(folder, 'install.py')
    if not (os.path.exists(python) and os.path.exists(install)):
        return ['the venv and weights']
    try:
        checked = subprocess.run([python, install, '--check'], cwd=folder,
                                 capture_output=True, text=True, timeout=600)
    except Exception:  # noqa: BLE001 - a slow disk must not crash the page
        logger.exception('could not check the AI install')
        return ['its packages (the check did not finish)']
    if checked.returncode == 0:
        return []
    labels = [line.strip() for line in (checked.stdout or '').splitlines()
              if 'MISSING' in line or 'PARTIAL' in line]
    return labels or ['some packages or weights']


def _start_ai_install(folder, missing):
    """Install what the AI is missing, in the background, once."""
    global _ai_install_proc
    if _ai_install_proc is not None and _ai_install_proc.poll() is None:
        return True

    logs = os.path.join(folder, 'logs')
    try:
        os.makedirs(logs, exist_ok=True)
        handle = open(os.path.join(logs, 'install.log'), 'ab')
    except OSError:
        handle = subprocess.DEVNULL

    venv_python = os.path.join(folder, '.venv', 'Scripts', 'python.exe')
    install = os.path.join(folder, 'install.py')
    if not os.path.exists(install):
        logger.error('%s has no install.py, so nothing can be installed', folder)
        return False
    if os.path.exists(venv_python):
        command = [venv_python, install]
    else:
        # No venv yet: build one with whatever Python this machine has, then
        # install into it. Without a Python there is nothing to run install.py.
        base = shutil.which('python') or shutil.which('py')
        if not base:
            logger.error('No Python on PATH, so song_service\.venv cannot be created')
            return False
        sheet = os.path.join(logs, 'install.cmd')
        with open(sheet, 'w', encoding='utf-8') as script:
            script.write('@echo off\r\n"%s" -m venv .venv || exit /b 1\r\n'
                         '".venv\\Scripts\\python.exe" install.py\r\n' % base)
        command = ['cmd.exe', '/c', sheet]

    logger.info('Installing the AI in %s: %s', folder, ', '.join(missing))
    _ai_install_proc = subprocess.Popen(
        command, cwd=folder, stdout=handle, stderr=handle,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return True


def _ensure_song_service():
    """Make the local model server ready; return a message when it is not."""
    if os.environ.get('SONG_SERVICE_URL'):
        # An explicit address (a tunnel, another machine) is not ours to manage.
        return None
    if _song_service_up():
        return None

    global _song_service_proc
    with _song_service_lock:
        if _song_service_up():
            return None
        folders = _song_service_dirs()
        if not folders:
            return ('The local AI is not installed: no song_service folder beside '
                    'the app. Run song_service\\install.py once, then try again.')
        for folder in folders:
            if not os.path.exists(os.path.join(folder, 'app.py')):
                continue
            python = os.path.join(folder, '.venv', 'Scripts', 'python.exe')
            if not os.path.exists(python):
                missing = _ai_missing(folder)
                if _start_ai_install(folder, missing):
                    return ('The local AI was not installed yet, so it is installing '
                            'now (missing: %s). This is a one-time download; retry '
                            'in a few minutes and the song will render.' % ', '.join(missing))
                continue

            missing = _ai_missing(folder)
            if missing:
                if _start_ai_install(folder, missing):
                    return ('The local AI is missing %s and is installing it now. '
                            'Retry in a few minutes.' % ', '.join(missing))
                continue
            logs = os.path.join(folder, 'logs')
            try:
                os.makedirs(logs, exist_ok=True)
                handle = open(os.path.join(logs, 'autostart.log'), 'ab')
            except OSError:
                handle = subprocess.DEVNULL
            env = dict(os.environ, SONG_PORT='8090')
            logger.info('Starting the local AI from %s', folder)
            _song_service_proc = subprocess.Popen(
                [python, 'app.py'], cwd=folder, env=env, stdout=handle, stderr=handle,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            # Loading starts fast (the pipeline is built on the first job), so
            # waiting for the port is enough; the song request itself can take
            # minutes and the proxy timeout already allows for that.
            for _ in range(90):
                if _song_service_up():
                    logger.info('Local AI is up on %s', SONG_SERVICE)
                    return None
                if _song_service_proc.poll() is not None:
                    logger.error('The local AI exited while starting; see %s', logs)
                    return 'The local AI stopped while starting; see song_service\\logs\\autostart.log'
                time.sleep(1)
            logger.error('The local AI did not answer on %s', SONG_SERVICE)
            return 'The local AI did not start within 90 seconds; see song_service\\logs'
        return 'The local AI is not installed; see song_service\\install.py'


def _warm_song_service():
    """Start the AI as the app launches, so the first click is not the wait.

    The page bounds its song request; spending that window on launching the
    service made a healthy AI look absent and fell back to the instrument-only
    song. Only warms a folder that already has a venv and weights, so a bare
    install is never triggered by simply opening the app.
    """
    for folder in _song_service_dirs():
        ready = (os.path.exists(os.path.join(folder, '.venv', 'Scripts', 'python.exe'))
                 and os.path.isdir(os.path.join(folder, 'models')))
        if ready:
            logger.info('Warming the local AI from %s', folder)
            _ensure_song_service()
            return


if getattr(sys, 'frozen', False):
    threading.Thread(target=_warm_song_service, daemon=True).start()


def _forward(path, method='GET', payload=None, stream=False):
    """One request to the song service, as a Flask response."""
    import urllib.error
    import urllib.request

    data = None
    headers = {}
    if payload is not None:
        import json as _json

        data = _json.dumps(payload).encode()
        headers['Content-Type'] = 'application/json'

    upstream = urllib.request.Request(SONG_SERVICE + path, data=data,
                                      headers=headers, method=method)
    try:
        with urllib.request.urlopen(upstream, timeout=SONG_TIMEOUT) as answer:
            body = answer.read()
            content_type = answer.headers.get('Content-Type', 'application/json')
            status = answer.status
    except urllib.error.HTTPError as exc:
        body = exc.read()
        content_type = exc.headers.get('Content-Type', 'application/json')
        status = exc.code
    except Exception as exc:  # noqa: BLE001 - the service being down is normal
        logger.warning('song service request failed: %s', exc)
        return jsonify({'error': 'The local AI service is not running. Start '
                                 'song_service/app.py, then try again.'}), 503

    if stream and status == 200:
        from io import BytesIO

        return send_file(BytesIO(body), mimetype=content_type,
                         as_attachment=False, download_name='song.wav')
    return app.response_class(body, status=status, mimetype=content_type)


@app.route('/api/lyrics', methods=['POST', 'OPTIONS'])
def api_lyrics():
    if request.method == 'OPTIONS':
        return ('', 204)
    problem = _ensure_song_service()
    if problem:
        return jsonify({'error': problem}), 503
    return _forward('/api/lyrics', 'POST', request.get_json(silent=True) or {})


@app.route('/api/song', methods=['POST', 'OPTIONS'])
def api_song():
    if request.method == 'OPTIONS':
        return ('', 204)
    problem = _ensure_song_service()
    if problem:
        return jsonify({'error': problem}), 503
    return _forward('/api/song', 'POST', request.get_json(silent=True) or {})


@app.route('/api/song/latest', methods=['GET', 'OPTIONS'])
def api_song_latest():
    """Let a reloaded page pick up the song the model is already singing."""
    if request.method == 'OPTIONS':
        return ('', 204)
    return _forward('/api/song/latest')


@app.route('/api/song/<token>', methods=['GET', 'OPTIONS'])
def api_song_status(token):
    if request.method == 'OPTIONS':
        return ('', 204)
    return _forward('/api/song/' + str(token)[:64])


@app.route('/song_file/<token>', methods=['GET', 'OPTIONS'])
def song_file(token):
    if request.method == 'OPTIONS':
        return ('', 204)
    return _forward('/song_file/' + str(token)[:64], stream=True)


@app.route('/last_song', methods=['GET', 'OPTIONS'])
def last_song_file():
    """The last rendered song, even after the app was closed and opened again."""
    if request.method == 'OPTIONS':
        return ('', 204)
    return _forward('/last_song', stream=True)


@app.route('/api/transcribe', methods=['POST'])
def api_transcribe():
    audio = request.get_data()
    if not audio:
        return jsonify({'error': 'Empty audio'}), 400
    if os.name != 'nt':
        return jsonify({'error': 'Offline transcription is only available on Windows'}), 503

    mime = (request.mimetype or '').split(';')[0]
    suffix = {'audio/webm': '.webm', 'audio/ogg': '.ogg', 'audio/wav': '.wav',
              'audio/mp4': '.m4a', 'audio/mpeg': '.mp3'}.get(mime, '.webm')

    wav = None
    try:
        wav = _audio_to_wav(audio, suffix)
        text = None
        try:
            text = _transcribe_with_whisper(wav)
        except Exception:
            logger.exception('Whisper failed; falling back to the Windows recogniser')
        if text is None:
            text = _recognize_wav(wav)
        return jsonify({'text': text})
    except Exception as exc:
        logger.exception('Transcription failed')
        return jsonify({'error': 'Transcription failed: %s' % exc}), 500
    finally:
        if wav and os.path.exists(wav):
            try:
                os.remove(wav)
            except OSError:
                pass


@app.after_request
def no_cache_for_pages(response):
    """The page and its data change with every release: never let the browser
    hold an old index.html that speaks a different Socket.IO protocol."""
    if response.mimetype in ('text/html', 'application/json'):
        response.headers['Cache-Control'] = 'no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
    return response


@app.route('/')
def index():
    try:
        logger.info("Serving index.html")
        index_path = os.path.join(static_folder, 'index.html')
        logger.debug(f"Index path: {index_path}")
        if os.path.exists(index_path):
            return send_file(index_path)
        else:
            logger.error(f"index.html not found at {index_path}")
            return "Error: index.html not found", 404
    except Exception as e:
        logger.error(f"Error serving index.html: {str(e)}")
        return f"Error: {str(e)}", 500

@app.route('/<path:path>')
def serve_static(path):
    try:
        logger.info(f"Serving static file: {path}")
        file_path = os.path.join(static_folder, path)
        logger.debug(f"Full file path: {file_path}")
        if os.path.exists(file_path):
            return send_file(file_path)
        else:
            logger.error(f"File not found: {file_path}")
            return f"File not found: {path}", 404
    except Exception as e:
        logger.error(f"Error serving static file {path}: {str(e)}")
        return f"Error: {str(e)}", 500

# Set up all routes and socket handlers
setup_routes(app, socketio)

if __name__ == '__main__':
    logger.info("Starting Flask-SocketIO server...")
    # PORT=0 (inherited from some launchers) would pick a random port and make
    # the server unreachable at the usual address, so fall back to 5001.
    port = int(os.environ.get('PORT') or 5001) or 5001
    logger.info(f"Server will run on port {port}")
    socketio.run(
        app,
        host='0.0.0.0',
        port=port,
        debug=False,
        allow_unsafe_werkzeug=True,
        use_reloader=False
    )
