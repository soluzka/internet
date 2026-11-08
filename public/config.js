// Where the download backend lives.
//
// Normally leave this empty. The Cloudflare Worker (worker.js) forwards
// /api/download and /download_file/... to the downloader service named by its
// DOWNLOAD_API variable, so the page stays same-origin and needs nothing here.
// When the page runs from the Python app, downloads already use that app.
//
// Set this only when the page is served somewhere without the Worker, for
// example a plain file server or another static host. Use the service URL with
// no trailing slash:
//
//   window.DOWNLOAD_API = 'https://video-downloader-xxxx.onrender.com';
//
window.DOWNLOAD_API = '';

// Where a song service lives, when not on this origin.
//
// The deployed site uses the Worker route, which calls the Cloudflare-hosted
// music model. A page opened on this machine also tries http://127.0.0.1:8090 by
// itself, where song_service/app.py runs ACE-Step on your GPU. Set this only to
// point at a service somewhere else (no trailing slash):
//
//   window.SONG_API = 'http://127.0.0.1:8090';
//
window.SONG_API = '';
