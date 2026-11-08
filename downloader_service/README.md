# Hosted downloader

The public page is static files on Cloudflare, so it has no Python and cannot
run yt-dlp. This is that missing piece: a small Flask app that downloads a video
and hands the file back, so the deployed page offers real downloads instead of
only opening the source page.

It is deliberately separate from the desktop app: no ML, no scraping, no voice
recognition, its own short dependency list. The page tries ports in order — the
desktop app on **5001**, then this service on **8080** — and remembers the one
that answered, so it works whether or not the app is running.

## API

```
POST /api/download          {"url": "https://..."}  -> 202 {"token": "...", "status": "queued"}
GET  /api/download/<token>                          -> {"status": "queued|downloading|processing|complete|error", "percent": 42.1, ...}
GET  /download_file/<token>                         -> the video file, then the job is deleted
GET  /health                                        -> {"ok": true, "max_height": 720, "cookies": false, "active_jobs": 0}
```

`/health` reports whether a cookie jar is loaded and how many jobs are active,
which is the quickest way to tell a bot-check refusal from a broken service.

Downloads are asynchronous because a real one outlasts the request timeout of
most hosts. The page starts a job, polls it for progress, then fetches the file.

## Deploy on Render

1. Push this repo to GitHub.
2. Render -> New -> Blueprint, choose the repo. `render.yaml` at the repo root
   builds `downloader_service/Dockerfile`.
3. Copy the service URL, e.g. `https://video-downloader-abc1.onrender.com`.
4. Put it in the Worker's `DOWNLOAD_API` variable — `wrangler.jsonc` or the
dashboard — and redeploy. The Worker then proxies `/api/download` and
   `/download_file/...`, so the page stays same-origin and needs no CORS. Only a
   page hosted without the Worker needs `window.DOWNLOAD_API` in
   `public/config.js` instead.
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
- **Impersonation matters.** yt-dlp is handed a browser fingerprint through
  `curl_cffi` (`YT_IMPERSONATE`, default `chrome`); without it the bot check
  bites far sooner. A plain string like `chrome` has to go through
  `ImpersonateTarget.from_str`, which is what `app.py` does — passing the bare
  string raises an empty `AssertionError`.
- `YT_COOKIES` takes the whole cookie jar as text, for hosts that only offer
  environment variables rather than a file mount. Neither form is committed.

## Run locally

```
powershell -NoProfile -ExecutionPolicy Bypass -File tools\start_services.ps1
```

That starts this service on 8080 and the song service on 8090, skipping whichever
is already answering — safe to run twice, and it is what the logon entry runs.
By hand:

```
.venv\Scripts\python.exe downloader_service\app.py
```

Listens on `PORT` (default 8080) with Flask's dev server. The container uses
gunicorn with a single worker: jobs live in that process's memory, so a second
worker would not see a job the first one started.

Logs go to `build\downloader_out.log` and `build\downloader_err.log` when the
launcher starts it hidden.
