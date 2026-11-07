import os
import sys
import logging
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
        logger.info(f'Loading Whisper model {WHISPER_MODEL}')
        _whisper_model = WhisperModel(WHISPER_MODEL, device='cpu', compute_type='int8')

    segments, _info = _whisper_model.transcribe(wav_path, beam_size=1, language='en', vad_filter=True)
    return ' '.join(segment.text.strip() for segment in segments).strip()


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
