# Hosted downloader

The public page is static files on Cloudflare, so it has no Python and cannot
run yt-dlp. This is that missing piece: a small Flask app that downloads a video
and hands the file back, so the deployed page offers real downloads instead of
only opening the source page.

It is deliberately separate from the desktop app: no ML, no scraping, no voice
recognition, its own short dependency list.

## API

```
POST /api/download          {"url": "https://..."}  -> 202 {"token": "...", "status": "queued"}
GET  /api/download/<token>                          -> {"status": "queued|downloading|processing|complete|error", "percent": 42.1, ...}
GET  /download_file/<token>                         -> the video file, then the job is deleted
GET  /health                                        -> {"ok": true}
```

Downloads are asynchronous because a real one outlasts the request timeout of
most hosts. The page starts a job, polls it for progress, then fetches the file.

## Deploy on Render

1. Push this repo to GitHub.
2. Render -> New -> Blueprint, choose the repo. `render.yaml` at the repo root
   builds `downloader_service/Dockerfile`.
3. Copy the service URL, e.g. `https://video-downloader-abc1.onrender.com`.
4. Put it in `public/config.js` as `window.DOWNLOAD_API` (no trailing slash),
   commit, and redeploy the Cloudflare site.
5. Press Download on the deployed page; the service log should show
   `POST /api/download`, the polls, then `GET /download_file/...`.

Free instances sleep after about 15 minutes idle, so the first download after a
pause waits a few seconds while the container wakes.

## The honest part

- **Cloud IPs fail most often.** YouTube in particular answers datacenter
  addresses with "Sign in to confirm you're not a bot". The same link downloads
  fine from the desktop app on a home connection. `YT_COOKIES_FILE` points the
  service at a cookies file if you want to push past some of that; it is never
  committed.
- `MAX_HEIGHT` (default 720) keeps files and bandwidth sane on small hosts.
- `MAX_ACTIVE_JOBS` / `MAX_JOBS_PER_IP` stop a public endpoint from being used
  as a free download farm; both answer `429` when hit.

## Run locally

```
.venv\Scripts\python.exe downloader_service\app.py
```

Listens on `PORT` (default 8080) with Flask's dev server. The container uses
gunicorn with a single worker: jobs live in that process's memory, so a second
worker would not see a job the first one started.
