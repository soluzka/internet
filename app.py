import os
import sys
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Add the scrape directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
scrape_dir = os.path.join(current_dir, 'scrape')
sys.path.insert(0, current_dir)
sys.path.insert(0, scrape_dir)

from flask import Flask, send_from_directory, send_file
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
    port = int(os.environ.get('PORT', 5001))
    logger.info(f"Server will run on port {port}")
    socketio.run(
        app,
        host='0.0.0.0',
        port=port,
        debug=False,
        allow_unsafe_werkzeug=True,
        use_reloader=False
    )
