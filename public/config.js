// Where the download backend lives.
//
// Empty means this page's own origin, which is what the desktop app wants: it
// serves both the page and /api/download on 127.0.0.1:5001.
//
// The deployed copy of this page is served from Cloudflare, which cannot run
// yt-dlp. Rather than sending every visitor through a hosted downloader, the
// page asks the desktop app on the same machine: a browser is allowed to reach
// http://127.0.0.1 from an https page, and the app answers CORS for any origin.
// So the download button works on the deployed site whenever the app is running
// there, and falls back to opening the video's original page when it is not.
//
// Point this somewhere else only to use a separate downloader service (no
// trailing slash):
//
//   window.DOWNLOAD_API = 'https://dl.example.com';
//
window.DOWNLOAD_API = 'http://127.0.0.1:5001';

// Where the song service lives, when not on this origin.
//
// Same reasoning as above: song_service/app.py runs ACE-Step and the lyric model
// on this machine's GPU and answers CORS, so the deployed page asks it directly
// at http://127.0.0.1:8090 instead of depending on a tunnel address that changes
// every time it restarts. Set this only to point at a service somewhere else
// (no trailing slash):
//
//   window.SONG_API = 'https://songs.example.com';
//
window.SONG_API = 'http://127.0.0.1:8090';
