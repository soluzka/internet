// Where the download backend lives.
//
// Leave this empty when the page is served by the Python app itself - downloads
// then use the same origin and nothing changes.
//
// When the page is exported as static files (Cloudflare, Netlify, a plain file
// server) there is no Python behind it, so downloads have to go to a separate
// hosted downloader. Put that service's URL here, without a trailing slash:
//
//   window.DOWNLOAD_API = 'https://video-downloader-xxxx.onrender.com';
//
window.DOWNLOAD_API = '';
