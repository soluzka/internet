# internet

A video search engine that works over its own library. It searches a local
SQLite index of scraped videos, learns from the links you click, asks each
listing which genre it belongs to, and downloads the videos you want.

It runs two ways from one codebase:

- **desktop app** — Flask + Socket.IO + SQLite on your machine, with live
  search, progress bars and yt-dlp downloads;
- **static site** — the same page served by a Cloudflare Worker from `public/`,
  searching a bundled index in the browser, with downloads handled by a small
  separately hosted service.

## The pieces

| Piece | What it does |
| --- | --- |
| `app.py` | Flask app: serves `public/`, socket stack, voice transcription |
| `ai_engine.py` | Scraper, SQLite/ML index, ranking, discovery worker, downloads, routes |
| `genre_model.py` | Infers a genre per video by questioning the listing |
| `public/` | The UI (`index.html`, styles, `config.js`, `data/videos.json`) |
| `tools/export_index.py` | Refreshes the committed index and precomputes genres |
| `worker.js` + `wrangler.jsonc` | Cloudflare Worker: static assets, voice, download proxy |
| `downloader_service/` | Small Flask container that runs yt-dlp for the static site |
| `data/video_index.db` | Committed snapshot of the index |

## Run it locally

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python app.py
```

Then open <http://127.0.0.1:5001>. `PORT` overrides the port, except `PORT=0`,
which falls back to 5001 so the server cannot end up on a random port.

Optional desktop build:

```bash
.venv\Scripts\python -m PyInstaller --clean --noconfirm ai_engine.spec
```

## How searching works

- **Matching has no cap.** A query matches videos whose title, description, tags
  or source contain its terms; results stream in batches of 200 with
  `search_completed` marking the end. There is no fixed result limit.
- **Ranking** combines term scores with click history, so links you use rise.
- **Discovery** runs in one background worker after a search: it scrapes the
  source sites for that query, stores new videos and reports how many were
  added. One worker keeps a burst of searches from saturating the machine.
- **The index grows by itself.** The live database is `../video_index.db`, next
  to the project folder; `data/video_index.db` is the committed snapshot.

### Genres

`genre_model.py` does not keyword-match. It asks each listing a set of questions
— does it name a scene or subgenre, which artists, which labels, bass, drums,
vocals, instruments, place, mood, tempo — and weights the answers by how rare
those phrases are across the whole library (IDF), so a distinctive word counts
more than a common one. Word-boundary matching keeps `dub` out of `dubstep`, and
a veto list of workshop/catalogue words stops non-music pages from being labelled
unless a strong music cue is present.

The percentage on a card is **decisiveness, not a probability**: it says how
clearly the questions were answered. `why?` on a chip shows the evidence.

On the desktop app the model fits in a background thread at startup (~8 s on a
large index) so startup is not delayed; inference is ~1.5 ms per video.

## The static site (Cloudflare)

`public/` is plain HTML/CSS/JS with no build step. The Worker serves it and
answers three things itself:

- `/api/transcribe` — voice search via Workers AI (`@cf/openai/whisper`);
- `/api/download`, `/download_file/...` — proxied to the download service
  (see below);
- everything else — the static files, with SPA fallback to `index.html`.

The page first tries Socket.IO (the desktop app). If it cannot connect it falls
back to the bundled index in `public/data/videos.json` and searches in the
browser, so the site works with no backend at all.

Deploy after refreshing the index:

```bash
.venv\Scripts\python tools\export_index.py   # DB snapshot + videos.json (+ genres)
npx wrangler deploy                          # or let Workers Builds deploy on push
```

This repo is connected to Cloudflare Workers Builds, which runs `bun install`
and deploys on push to `main`. `package.json` declares `socket.io-client`; the
browser bundle is committed at `public/vendor/socket.io.min.js` so the page
needs no CDN and works even if a build installs nothing.

**The static index is a snapshot.** Search results and genres on the deployed
site are frozen at export time; scraped videos appear there only after running
the exporter again and redeploying. Genres must be precomputed because the
browser has no Python to ask.

## Songs and lyrics on the deployed site

The website makes songs itself — no local machine, no tunnel. The Worker owns
both halves of it:

| Route | What it does | Model |
| --- | --- | --- |
| `POST /api/lyrics` | writes the words for the track | `@cf/meta/llama-3.1-8b-instruct` |
| `POST /api/song` | sings those words over music built from your search | `minimax/music-2.6` |
| `GET /api/song-file` | streams the returned audio same-origin | — |

The page calls `/api/lyrics` first, then `/api/song`, and only falls back to the
browser synthesiser when neither answers (a plain static host, or a machine with
no model service). On the deployed Worker both answer.

### What the Cloudflare build needs

1. **The AI binding.** `wrangler.jsonc` already declares it:

   ```jsonc
   "ai": { "binding": "AI" }
   ```

   It is a binding, not an npm package: there is nothing extra to install, and
   `env.AI.run(model, input)` reaches Cloudflare's hosted models.
2. **Workers AI turned on for the account**, with credit. Open the Cloudflare
   dashboard → Workers AI and enable it. Billing is per use: roughly **$0.15 per
   song** and **$0.01 per lyric set**.
3. **The deploy itself**, which installs the build tool and ships the Worker:

   ```bash
   npx wrangler deploy
   ```

   Workers Builds does the same on push to `main`: it runs `bun install` (which
   now also installs `wrangler` from `devDependencies`) and deploys. Nothing in
   `song_service/` is uploaded — that directory is local-only.

If the account has no Workers AI, `/api/lyrics` and `/api/song` answer `503`
with a readable message and the page falls back to the synthesiser, so a deploy
never breaks the site.

### ACE-Step cannot be installed on Cloudflare

Worth stating plainly, because it comes up: ACE-Step is Python, PyTorch and a
3.5B checkpoint — Workers run JavaScript/WASM only, and need CUDA for that model.
It cannot be packaged into the Worker. The two supported shapes are:

- **on the website** — the hosted models above, which ship with the deploy;
- **on this machine** — `song_service/` (ACE-Step, free per song), where the
  page reaches it at `http://127.0.0.1:8090` because the page itself is local.

## Downloads on the deployed site

Static hosting cannot run yt-dlp, so downloads need a real backend. That is
`downloader_service/` — Flask, yt-dlp and a bundled ffmpeg, no ML, its own short
dependency list.

```
POST /api/download          {"url": "..."}  -> 202 {"token": "...", "status": "queued"}
GET  /api/download/<token>                  -> {"status": "queued|downloading|processing|complete|error", "percent": ...}
GET  /download_file/<token>                 -> the video file, then the job is deleted
GET  /health                                -> {"ok": true}
```

Downloads are asynchronous because one outlasts the request timeout of most
hosts: the page starts a job, polls it for progress, then fetches the file.

To turn it on:

1. Deploy the service somewhere that runs Docker — Render's free tier works and
   `render.yaml` at the repo root is a ready blueprint (New → Blueprint → pick
   the repo).
2. Put its URL in the Worker's `DOWNLOAD_API` variable — either in
   `wrangler.jsonc`, or in the dashboard under Settings → Variables. The Worker
   then proxies `/api/download` and `/download_file/...` to it, so the page stays
   same-origin and needs no CORS.
3. Only if the page is hosted somewhere without the Worker, set
   `window.DOWNLOAD_API` in `public/config.js` instead; the page then calls the
   service directly.

The same page works against the desktop app with nothing configured, because
there the app answers on its own origin.

### The honest limits

- **Cloud IPs get refused.** YouTube answers datacenter addresses with "Sign in
  to confirm you're not a bot". The identical link usually downloads fine from
  the desktop app on a home connection. `YT_COOKIES_FILE` can help; never commit
  that file.
- Free instances sleep when idle, so the first download after a pause waits a
  few seconds for the container to wake.
- The service caps work so a public endpoint cannot be used as a free download
  farm: `MAX_HEIGHT` (720 by default), `MAX_ACTIVE_JOBS`, `MAX_JOBS_PER_IP`.

## Voice search

The microphone button records a clip and sends it for transcription. Locally it
uses faster-whisper, falling back to the Windows speech recogniser; on the
Worker it uses Workers AI. Silence below a confidence threshold is ignored
rather than turned into a query.

## API

**Socket.IO events** (desktop app): `search_query` → `search_results`,
`search_completed`, `search_error`; `client_protocol` negotiates batching;
`discovery_results`; `record_click`; `get_stats`; `download_video` →
`download_progress`, `download_complete`, `download_error`.

**HTTP**: `POST /api/search`, `GET /api/stats`, `POST /api/download`,
`GET /download_file/<token>`, `POST /api/transcribe`.

## Configuration

| Variable | Where | Meaning |
| --- | --- | --- |
| `PORT` | app | Port for the desktop app (default 5001) |
| `WHISPER_MODEL` | app | Local speech model (default `base.en`) |
| `RENDER` | app | Set by Render; skips ML rebuilds and uses eventlet |
| `DOWNLOAD_API` | Worker | URL of the download service |
| `MAX_HEIGHT` | downloader | Download resolution cap (default 720) |
| `MAX_ACTIVE_JOBS` / `MAX_JOBS_PER_IP` | downloader | Concurrency limits |
| `YT_COOKIES_FILE` | downloader | Optional yt-dlp cookies file |

## Troubleshooting

- **"database is locked"** — the connections use WAL and a 30 s busy timeout;
  the app and the exporter can both touch the database safely.
- **Genres missing on the live site** — run `tools/export_index.py`, confirm it
  prints `genres N/M`, then redeploy.
- **Download answers 405 or opens the source page** — `DOWNLOAD_API` is unset or
  unreachable; the page falls back to the original link.
- **Voice search does nothing** — the microphone needs a secure origin (https or
  localhost). On a LAN IP the browser blocks it.

`vercel.json` is a leftover deployment target that routes everything to
`app.py`; the Cloudflare Worker is the supported static deployment.
