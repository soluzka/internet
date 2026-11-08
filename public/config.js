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
