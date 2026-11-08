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
| `song_service/` | The local lyric and music models (GPU, 8090) |
| `start.cmd` / `start.ps1` | One click: song service, site and tunnel |
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

## Songs and lyrics

The AI in this project is **local only**. There is no Workers AI binding, no
hosted model call and nothing billed per track: `worker.js` serves the static
page and proxies downloads, and that is all it does.

The page asks two things of `song_service/`, which runs on your own machine:

| Route (on 127.0.0.1:8090) | What it does | Model |
| --- | --- | --- |
| `POST /api/lyrics` | writes the words | Qwen 2.5 1.5B Instruct |
| `POST /api/song` | sings those words | ACE-Step v1 3.5B |

The page calls the service on `127.0.0.1:8090` when it is opened from this
machine, and falls back to the sampled band in the browser when the service is
not running. On the deployed site the page reaches the same service through a
Quick Tunnel — see below — or plays the band if nothing answers.

### Start everything with one click

`start.cmd` (which runs `start.ps1`) brings up the whole stack in order and
leaves anything already running alone, so double-clicking it twice is safe:

1. `song_service/app.py` on **8090** — the lyric model and ACE-Step on the GPU;
2. `app.py` on **5001** — the site on this machine;
3. `cloudflared` — a Quick Tunnel giving the service a public `https` address;
4. the browser, at <http://127.0.0.1:5001>.

The tunnel's address is printed and copied to the clipboard. It changes every
time the tunnel restarts.

> A config.yml in `~/.cloudflared` disables Quick Tunnels: its ingress rules win
> over `--url` and the catch-all answers **404**, so nothing reaches the service.
> `start.ps1` therefore runs cloudflared with `--config tools/bin/quick-tunnel.yml`,
> an empty config that keeps the tunnel bound to port 8090. `cloudflared.exe`
> itself is downloaded into `tools/bin/` and gitignored (55 MB).

### Pointing the live site at the model

The model address is a runtime setting, not a build setting, because the tunnel
address changes on every restart:

1. run `start.cmd` and copy the `https://….trycloudflare.com` address it prints;
2. on the live site press **Song designer**, then **Connect my model**, and paste
   it in. The song re-renders using it immediately.

The address is kept in this browser under `songApi` in `localStorage`, tried
before the same-origin route and before 8090, so the deployed page sings without
a rebuild. Paste an empty value to forget it.

To give the deployed page a default instead, set `SONG_API` on the Worker, in
one of two places:

- **Dashboard:** Workers & Pages → `browser` → Settings → Variables and Secrets →
  **Add** → name `SONG_API`, value the tunnel origin → Save. Then Deploy for the
  variable to be picked up by that version.
- **Repo:** the `vars` block in `wrangler.jsonc`, applied by the next deploy.

Either way the value is the **origin only** — `https://name.trycloudflare.com`,
with no trailing slash and no path, because the Worker and the page append
`/api/song` themselves. A pasted address in the page still wins over it.

Note that a Quick Tunnel address changes on every restart, so a stored default
goes stale: after restarting `start.cmd`, paste the new address in the page (or
update `SONG_API`). A named tunnel on a domain you own gives one hostname that
survives restarts, at the cost of a `cloudflared tunnel login`.

Cross-origin calls already work: `song_service` sends
`Access-Control-Allow-Origin` and answers the JSON preflight with 204, so the
page's `POST /api/song` is not blocked from the Worker's origin.

The honest limits: the tunnel is only up while your PC, the service and
`cloudflared` are all running; Quick Tunnels have no uptime guarantee and are
meant for development; and anything holding the address can render songs on your
GPU, since `/api/song` has no authentication.

### What the deploy needs

Nothing AI-related. `wrangler.jsonc` declares no `ai` binding and the Worker
makes no model calls:

```bash
npx wrangler deploy
```

Workers Builds does the same on push to `main`: it runs `bun install` (which
installs `wrangler` from `devDependencies`) and deploys. Nothing in
`song_service/` is uploaded — that directory is local-only and gitignored for
models.

No build step involves the model address: `SONG_API` is optional and the page
can take one at runtime, so pointing the site at a new tunnel never needs a
redeploy.

### ACE-Step cannot be installed on Cloudflare

Worth stating plainly, because it comes up: ACE-Step is Python, PyTorch and a
3.5B checkpoint — Workers run JavaScript/WASM only, and need CUDA for that model.
It cannot be packaged into the Worker, so the only place it runs is
`song_service/` on this machine.

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
| `SONG_API` | Worker | Optional default origin of the song service; a pasted address in the page wins |
| `songApi` | browser (`localStorage`) | The model address pasted into "Connect my model" |
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
- **The live site plays the band but never sings, and there is no "Connect my
  model" button** — the deployed page is older than `1ea803f`; redeploy so the
  page can take a model address at runtime.
- **The tunnel answers 404 with no body** — cloudflared picked up
  `~/.cloudflared/config.yml`. Run the tunnel with
  `--config tools\bin\quick-tunnel.yml` as `start.ps1` does.

`vercel.json` is a leftover deployment target that routes everything to
`app.py`; the Cloudflare Worker is the supported static deployment.
