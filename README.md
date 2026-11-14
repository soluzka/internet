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
| `worker.js` + `wrangler.jsonc` | Cloudflare Worker: static assets, Workers AI voice, download and song proxies |
| `downloader_service/` | Small Flask container that runs yt-dlp for the static site |
| `song_service/` | The local lyric and music models (GPU, 8090) |
| `tools/start_services.ps1` | The one launcher: downloader, song service, site, tunnel, publishes the address, keeps `songsvc://` registered |
| `tools/install_autostart.ps1` | Adds the logon entry and starts the watchdog, so both return and stay up |
| `tools/register_protocol.ps1` | Registers `songsvc://` so the site's Start the AI button can launch it |
| `start.cmd` / `start.ps1` | One click for the same launcher, then opens the site |
| `data/video_index.db` | Committed snapshot of the index |
| `build/` | The check scripts: what a build generates is ignored, the scripts are not — see below |

### The `build/` folder

The scripts in here are tracked, so the checks move with the repository. What a
build *generates* stays local, because no commit can hold it: `ai_engine/` is
PyInstaller's work folder with a 314 MB package in it, and `wrangler-tool/` is
the portable Node install with a 103 MB `workerd.exe`, and GitHub refuses any
file over 100 MB. Captured logs, test audio, JSON payloads and the
`commit_msg*.txt` notes are left out for the same reason a receipt is not kept
with the product.

The ones worth knowing about:

| Script | What it checks |
| --- | --- |
| `deploy_and_check.ps1` | Deploys, then confirms the new version serves the page |
| `verify_live.ps1` | The live page holds this build, and the repo is clean |
| `asset_check.ps1` | Each `public/` file is served with the right content type |
| `service_state.ps1` | Both local services, with the GPU answer from `/health` |
| `autostart_status.ps1` | Startup entry, `songsvc://` target, services now |
| `race_test.ps1` | Two launcher runs leave exactly one song service |

They resolve the repo root from their own location, so any of them runs from
wherever you are. `race_test.ps1` restarts the song service; run it when nothing
is rendering.

### The index on the site

The 8,724 videos live in a Cloudflare D1 database (`video-index`, bound as `DB`
in `wrangler.jsonc`), and `/api/search` answers from it. The page asks for sixty
rows per search instead of downloading `public/data/videos.json` — three
megabytes the browser used to fetch in full before it could show one card.

```
GET /api/search?q=dubstep+mix&limit=60&log=1
{ "query": "dubstep mix", "total": 69,
  "library": { "total_videos": 8724, "total_searches": 114, "total_clicks": 55 },
  "videos": [ { "u": "…", "t": "…", "th": "…", "c": 1 } ] }
```

Every word has to appear in the row, so two words narrow rather than widen, and
the order prefers what people clicked. `log=1` is sent by the page only: a real
search is written to `search_history`, a crawler following the URL is not.

`public/data/videos.json` stays as the fallback for a copy of the page with no
database behind it. To push the SQLite file's contents up after a change:

```
python build/export_d1.py
build/wr.ps1 d1 execute video-index --remote --file build/d1_import.sql
```

`build/wr.ps1` is wrangler via the portable Node in `build/wrangler-tool`, which
is how this project deploys without a global install.

## Run it locally

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python app.py
```

Then open <http://127.0.0.1:5001>. `PORT` overrides the port, except `PORT=0`,
which falls back to 5001 so the server cannot end up on a random port.

### What `requirements.txt` installs

One file, and none of it is the music model — that lives in `song_service/`
with its own manifest. This is the web app:

| Group | Packages | Why |
| --- | --- | --- |
| Web framework | `Flask`, `Flask-Cors`, `Flask-SocketIO`, `python-socketio`, `python-engineio` | The site, its socket stack and the live search stream |
| HTTP clients | `aiohttp`, `requests` | Scraping the source sites |
| Video downloads | `yt-dlp`, `yt-dlp-ejs`, `curl-cffi`, `imageio-ffmpeg` | yt-dlp plus the impersonation and ffmpeg it needs |
| HTML parsing | `lxml` | Listings are parsed with lxml; there is no BeautifulSoup |
| Ranking | `numpy`, `scipy`, `scikit-learn` | The ML index behind search order and genre inference |
| Voice search | `faster-whisper` | Local transcription; the app falls back to the Windows recogniser without it |
| Build | `wheel`, `setuptools`, `pyinstaller`, `pyinstaller-hooks-contrib` | Only needed to freeze the desktop executable |

**Install into a virtual environment, always.** A partially installed or broken
global interpreter makes PyInstaller freeze an empty package, which is what
produces `cannot import name 'emit' from 'flask_socketio'` in the frozen app.
Check the socket stack before building:

```bash
.venv\Scripts\python -c "from flask_socketio import emit, SocketIO"
```

Optional desktop build:

```bash
.venv\Scripts\python -m PyInstaller --clean --noconfirm ai_engine.spec
```

That freezes `app.py` into `dist/ai_engine.exe`, bundling `public/` and
`cinema.ico` per `ai_engine.spec`. The executable runs the same Flask app and
opens on the same port; it does **not** bundle the song models, which stay in
`song_service/` and are reached over HTTP exactly as the browser does.

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

The song AI is **local only**: ACE-Step is a 3.5B checkpoint that needs CUDA, and
Workers AI has no music model in its catalog, so nothing on Cloudflare can render
a track. Workers AI does handle **voice search** (`@cf/openai/whisper`), which is
the one model that genuinely runs in the site.

The page asks two things of `song_service/`, which runs on your own machine:

| Route (on 127.0.0.1:8090) | What it does | Model |
| --- | --- | --- |
| `POST /api/lyrics` | writes the words | Qwen 2.5 1.5B Instruct |
| `POST /api/song` | sings those words | ACE-Step v1 3.5B |

Both models pick their device themselves: the lyric model runs on CUDA when
torch can see a card and in system RAM when it cannot. On the GPU the lyric model
is loaded only after the song model has been released, because 7.9 GB of ACE-Step
and 3 GB of Qwen do not fit in 8 GB together and paging between them cost more
than reloading — measured here, a lyric request went from **3m42s to 10.5s**.

`GET /health` reports what is running where:

```json
{"ok": true, "device": "cuda", "gpu": "NVIDIA GeForce RTX 4060 Ti",
 "vram_gb": 8.0, "loaded": true, "lyrics_loaded": true, "cpu_offload": true}
```

The page calls the service on `127.0.0.1:8090` and falls back to the sampled band
in the browser when the service is not running. It also stops asking the Worker
for the song model after the first 501, so a compose goes straight to the machine
that can actually render.

### Installing the AI packages

The song service keeps its own environment, separate from the web app's venv,
because its dependencies are heavy and its CUDA wheels must not leak into the
Flask app. From the repo root:

```bash
cd song_service
python -m venv .venv
.venv\Scripts\python install.py --check      # report what is present, change nothing
.venv\Scripts\python install.py              # packages, then weights
```

`install.py` reads `song_service/models.json`, which is the one place versions
are declared — a bump is a manifest edit, not a hand-run pip command.

| Invocation | What it does |
| --- | --- |
| `--check` | Prints which packages import and which weights are on disk |
| `--packages` | pip-installs from the manifest: `torch`/`torchaudio` from the **cu126** index, `transformers==4.57.6`, `huggingface-hub==0.36.2`, ACE-Step from git, flask, flask-cors, soundfile, librosa, hf_transfer |
| `--weights` | Downloads ACE-Step v1 3.5B (~7 GB) and Qwen2.5-1.5B-Instruct (~3.1 GB) into `song_service/models/` |
| *(no flag)* | Both, packages first |

Things worth knowing before you start it:

- **No CUDA toolkit install.** On Windows the NVIDIA driver (560 or newer)
  provides the runtime and the cu126 torch wheel carries its own CUDA libraries.
  PyPI's default `torch` on Windows is CPU-only, which is why the index is
  declared per package in the manifest rather than left to pip's defaults.
- **Weights are resumable.** About 10 GB in total, gitignored under
  `song_service/models/`. Rerun `--weights` after an interruption: a partial
  folder is measured and continued rather than started over.
- **Verify the GPU** before blaming the app:
  `.venv\Scripts\python -c "import torch; print(torch.__version__, torch.cuda.is_available())"`
  should print `2.14.1+cu126 True`.
- **The web app's dependencies are separate.** Flask, the socket stack,
  faster-whisper and yt-dlp come from the root `requirements.txt` in the root
  venv; `song_service/` needs none of them, and the root app needs no torch.

### Start everything with one click

`start.cmd` (which runs `start.ps1`, a thin wrapper around
`tools/start_services.ps1`) brings up the whole stack in order and leaves
anything already running alone, so double-clicking it twice is safe:

1. `downloader_service/app.py` on **8080** — yt-dlp, Top 100 and the player;
2. `song_service/app.py` on **8090** — the lyric model and ACE-Step on the GPU;
3. `app.py` on **5001** — the site on this machine;
4. `cloudflared` — a Quick Tunnel giving the machine a public `https` address;
5. the browser, at <http://127.0.0.1:5001>.

The tunnel's address is printed **and published to the site**, so nothing has to
be pasted into a phone or a second computer. It changes every time the tunnel
restarts, and each run re-publishes the new one:

- `POST /api/song/endpoint` with `{"url": "https://….trycloudflare.com"}` and the
  header `x-song-key: <value of SONG_ENDPOINT_KEY>` stores it in the `STATS` KV
  namespace under `song_api`. A write without that header answers **403**.
- `GET /api/song/endpoint` is public and returns the stored address, which is what
  the page reads on load before probing anything.

So the pairing is: the PC owns the tunnel and the key, the site only remembers
the last address it was told. If the address looks stale, run
`tools\start_services.ps1` again — it republishes — and reload the page, which is
the only step a phone needs.

`tools\start_services.ps1 -NoTunnel` skips the tunnel entirely when you only want
the local services.

> A config.yml in `~/.cloudflared` disables Quick Tunnels: its ingress rules win
> over `--url` and the catch-all answers **404**, so nothing reaches the service.
> The launcher therefore runs cloudflared with `--config tools/bin/quick-tunnel.yml`,
> an empty config that keeps the tunnel bound to port 8090.

`cloudflared.exe` is gitignored (53 MB), so a fresh clone has none. The launcher
fetches it once on first run, at a pinned version
(`$cloudflaredVersion = '2026.10.7'`), into a `.download` file first: Windows'
signature check must report **Valid** *and* name Cloudflare, or the file is
discarded and the tunnel is skipped with a line saying so. Nothing unpinned is
ever executed, and `latest` is deliberately not used. On 14 Nov 2026 the fetch
took 28 seconds from a clone with no binary at all, then the tunnel started and
published its address.

### Starting the AI from the site

The deployed page is on Cloudflare, the song AI is on your PC, and a browser tab
cannot start a program. Windows can, so the header carries a **Start the AI**
button that navigates to `songsvc://start`; that scheme is registered for the
current user (HKCU, no administrator) and points at `tools/start_services.ps1`.

What the click does, in order: Windows runs the launcher, the launcher starts the
downloader, the song service with `SONG_WARM=1` and the tunnel, and the page polls
`/health` — every five seconds while it is off or warming, every thirty once it is
up — until the button reads **AI ready**.

Next to it a badge reports what the render will use, read from `/health` rather
than guessed, and it separates *answering* from *ready* because the two are about
fifty seconds apart on this machine:

| `/health` says | Badge | Button |
| --- | --- | --- |
| `loaded: true`, `device: "cuda"` | `CUDA · GeForce RTX 4060 Ti`, green | `AI ready` |
| `loaded: false`, `warming_seconds: 95` | `CUDA · warming 1m 35s`, amber | `AI warming…` |
| nothing answers, but it did in the last four minutes | `CUDA · busy loading` | `AI warming…` |
| `device: "cpu"` | `CPU only`, amber | `AI ready` |
| nothing answers and nothing recent | `AI off` | `Start the AI` |

Measured on 13 Nov 2026: **51 seconds** from process start to `loaded: true` with
nothing competing. Any five-to-ten-minute wait is a restart, not the model — the
launcher used to probe `/health` with a three-second limit, call a busy service
dead, and start a rival copy that could not bind 8090, which restarted the warm.
The probe now allows twenty seconds and the song service runs `AboveNormal` so the
site fitting its own models does not starve it.

A compose pressed during the warm is not dropped: the page waits up to three
minutes for the service to answer, counting in the status line, instead of falling
back to a song with no AI in it.

![The header: Start the AI beside Song designer, and the CUDA badge reading the card from /health](public/gpu-chip.png)

Four things start it, and none of them need you to run a script:

| Trigger | How |
| --- | --- |
| Clicking **Start the AI** | `songsvc://` → `tools/start_services.ps1` |
| Logging in to Windows | `HKCU\...\Run` key and Startup entry, from `tools/install_autostart.ps1` |
| A service dying while the PC stays on | The watchdog re-runs the launcher within two minutes |
| Running it by hand | `tools/start_services.ps1` (safe to repeat) |

The launcher repairs the `songsvc://` registration on every run — missing, or
pointing at a folder that has moved — so the button keeps working without
re-registering. It writes one line per run to `build\launcher_trace.txt`, which
is how "the site started it" can be checked rather than assumed.

#### Is the autostart installed? Is it right?

These are the checks to run when a boot looks like nothing happened. The full
transcript of the last run is `build\launcher_run.log`; the one-line-per-run
history is `build\launcher_trace.txt`.

```powershell
# every registered trigger, the watchdog, and whether the services answer now
powershell -NoProfile -ExecutionPolicy Bypass -File build\autostart_status.ps1

# the two entries on their own
(Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'AI song services').'AI song services'
Test-Path (Join-Path ([Environment]::GetFolderPath('Startup')) 'AI song services.cmd')

# was there a run at logon? compare a boot with the trace
(Get-CimInstance Win32_OperatingSystem).LastBootUpTime
Get-Content build\launcher_trace.txt -Tail 5
```

A boot on 13 Nov 2026 read: boot `21:25:34` → `launcher ran 21:26:10` →
`watchdog started 21:26:25` → tunnel published → `/health` `loaded: true` at
`21:52`-ish. If the trace has no line within a minute of the boot time, the entry
did not run; re-install it:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_autostart.ps1
```

That is safe to repeat: it writes the same two entries and reuses a running
watchdog instead of adding a second one.

None of these is Task Scheduler, because registering a task returns *Access
denied* without administrator rights. The logon entry is a Run key plus the
Startup folder entry, and the watchdog is the launcher started with `-Watch`: it
sleeps two minutes at a time and restarts a service whose port has nothing behind
it. A port with a process behind it is left alone, so a service that is still
importing torch is never started twice. Verified on 8 Nov 2026: the song service
was killed outright and `/health` answered again 18 seconds after the watchdog
noticed.

That logon entry matters because the Startup folder alone has already failed
here: on 8 Nov 2026 the PC booted at 18:41:26, Explorer logged in at 18:41:38,
and the entry produced no run at all until the launcher was called by hand.

Three things it cannot do: start anything on a machine where the scheme is not
registered (your phone, another computer), start a local program without a click
— browsers only allow `songsvc://` from a user gesture, so opening the page can
detect the AI but not boot it — and render a song without the PC, since no
Cloudflare model composes music, as the section further down explains.

The badge is the quickest way to answer "is it actually on the GPU?" — it says
so in the header, from the service's own answer, without opening a console.

### If the site must reach this machine over the internet

Everything above works because the page runs on the same computer as the model.
A phone or another laptop needs a public address to reach instead, which the
tunnel started by `tools/start_services.ps1` provides.

**Nothing has to be pasted.** The launcher publishes the address it was given to
the Worker (`POST /api/song/endpoint`, key `SONG_ENDPOINT_KEY`) after every start,
and the page asks for it on load. That is why a new tunnel name still works on a
phone after a reload and not after anything else.

### What the tunnel carries

The tunnel points at **8090**, the song service. That service also forwards to the
downloader on loopback, so one address covers everything a phone cannot reach:

| Path | Reaches | Used for |
| --- | --- | --- |
| `/api/song`, `/api/song/<token>`, `/song_file/<token>` | the song service itself | composing, progress, saving |
| `/api/lyrics`, `/health` | the song service itself | lyrics, the badge |
| `/api/top` | downloader **8080** | the Top 100 button |
| `/pc/<anything>` | downloader **8080** | `api/play`, `download_file`, progress — TikTok and Dailymotion playback |

yt-dlp has to run on this machine (YouTube refuses a datacentre address), so the
file is fetched here and streamed back through that path — `Range` is forwarded,
which is what lets the player seek. Without the `/pc` route a phone can play
YouTube, whose embed is remote, and nothing else.

### If the address goes stale

A Quick Tunnel gets a new name whenever `cloudflared` restarts, so the stored
address can point at nothing. The symptoms are a phone that says **AI off**, a Top
100 that returns "the downloader on this PC is not answering", or a video that
will not start, while the PC itself is fine.

1. Run `tools\start_services.ps1`. It starts or reuses the tunnel and republishes
   the current address by itself.
2. Check what the site now holds: `curl https://<your worker>/api/song/endpoint`.
3. Reload the page on the phone. The new address is only read on load.

To publish by hand, with the key from the Worker's secrets:

```bash
printf '{"url":"https://name.trycloudflare.com"}' > endpoint.json
curl -X POST https://<your worker>/api/song/endpoint \
  -H 'Content-Type: application/json' \
  -H "x-song-key: $SONG_ENDPOINT_KEY" \
  --data-binary @endpoint.json
```

Use `--data-binary @file` rather than inline JSON: on PowerShell, quoting inline
JSON through curl mangled it and the site rejected the write.

A named tunnel on a domain you own removes this problem entirely — one hostname
that survives restarts — at the cost of a `cloudflared tunnel login` and DNS.

The address is also kept per browser under `songApi` in `localStorage` when
someone pastes it into **Song designer → Connect my model**. That value is tried
before the published one and wins over it; paste an empty value to forget it.

To give the deployed page a default instead, set `SONG_API` on the Worker, in
one of two places:

- **Dashboard:** Workers & Pages → `browser` → Settings → Variables and Secrets →
  **Add** → name `SONG_API`, value the tunnel origin → Save. Then Deploy for the
  variable to be picked up by that version.
- **Repo:** the `vars` block in `wrangler.jsonc`, applied by the next deploy.

Either way the value is the **origin only** — `https://name.trycloudflare.com`,
with no trailing slash and no path, because the Worker and the page append
`/api/song` themselves. A pasted address in the page still wins over it.

`SONG_API` is only a fallback for a site that has never been told about a tunnel,
because a published address replaces it as the page's first choice. Leave it unset
unless you run a named tunnel with a hostname that does not change.

Cross-origin calls already work: `song_service` sends
`Access-Control-Allow-Origin` and answers the JSON preflight with 204, so the
page's `POST /api/song` is not blocked from the Worker's origin.

The honest limits: the tunnel is only up while your PC, the service and
`cloudflared` are all running; Quick Tunnels have no uptime guarantee and are
meant for development; and anything holding the address can render songs on your
GPU and use `yt-dlp` through `/pc`, since none of it has authentication. Sleeping
is part of that list — this PC is set to sleep after fifteen minutes on power,
which takes the tunnel and the model off the network until it wakes.

### What the deploy needs

One Workers AI binding and no secrets. `wrangler.jsonc` declares
`"ai": {"binding": "AI"}`, which voice search uses on the free allowance:

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

The shortest route needs no hosting at all: the tunnel on this machine already
carries the downloader under `/pc`, which is what makes **Top 100** and TikTok or
Dailymotion playback work on a phone. Nothing to deploy, nothing to paste — just
`tools\start_services.ps1` with the tunnel up.

To run it on a host instead:

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
  few seconds for the container to wake. `https://<your worker>/api/health`
  says whether the service is configured, reachable and holding cookies, which
  is faster than diagnosing a failed download.
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
| `YT_COOKIES` | downloader | The same cookie jar as text, for hosts that only give you environment variables |
| `SONG_WARM` | song service | `1` loads the song model at startup instead of on the first song (set by the launcher) |
| `LYRICS_DEVICE` | song service | `cuda` or `cpu` for the lyric model; unset means cuda when torch sees a card |
| `ACE_CPU_OFFLOAD` / `ACE_DTYPE` | song service | Page the weights in and out (default `1`), and the model dtype (default `bfloat16`) |
| `ACE_STEPS` / `ACE_MAX_SECONDS` | song service | Diffusion steps (30) and the ceiling on song length (120 s) |
| `SONG_ENDPOINT_KEY` | Worker secret | Proves a tunnel publish came from this PC; `POST /api/song/endpoint` without it is **403** |
| `x-song-key` | request header | The same key, sent by the launcher when it publishes |
| `/api/health` (Worker) | Worker | Reports whether the download service is configured, awake and holding a cookie jar |
| `/health` (song service) | song service | `device`, `gpu`, `vram_gb`, `loaded`, `warming`, `warming_seconds`, `warm_failed`, `lyrics_loaded` |
| `/api/song/endpoint` | Worker | The tunnel address the PC last published; `GET` is public, `POST` needs `x-song-key` |
| `/pc/<path>` | song service | Forwards to the downloader on 8080, so a phone can use Top 100, the player and downloads |

## Setting up on another PC

Three Python environments, not one, and they differ in who creates them. Nothing
here travels in a clone: every `.venv` is gitignored, as are the models.

| Environment | Who creates it | Command |
| --- | --- | --- |
| `downloader_service\.venv` | **the launcher, by itself** | none — it runs `python -m venv` and installs `downloader_service\requirements.txt` the first time |
| `.venv` (root, the site) | **you** | `python -m venv .venv` then `.venv\Scripts\python -m pip install -r requirements.txt` |
| `song_service\.venv` | **you**, before `install.py` | `python -m venv song_service\.venv` then `song_service\.venv\Scripts\python install.py` |

The song service is the awkward one: `install.py` installs the CUDA torch wheel
and the 10 GB of weights, but it does not create the venv it runs in, and the
launcher refuses to invent one — it says *"run song_service\install.py first (it
installs the CUDA torch)"* instead of starting a CPU-only service that would take
minutes per song.

So a fresh machine is:

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
python -m venv song_service\.venv
song_service\.venv\Scripts\python install.py          # packages, then ~10 GB of weights
powershell -NoProfile -ExecutionPolicy Bypass -File tools\start_services.ps1
```

The launcher then handles the downloader's venv, and fetches `cloudflared` if it
is missing. What it cannot supply is `build\song_endpoint.key`: without it the
tunnel runs but the site is never told the address, so a phone still reports the
AI as off. Copy that file across, or set `SONG_ENDPOINT_KEY` on the Worker to a
new value and write the same value into the file.

### Do not copy a venv between machines

A venv is not portable: `pyvenv.cfg` holds an absolute `home` path to the
interpreter that built it, and every script in `Scripts\` is a stub ending in that
path too. This repository has already been bitten once — when the Windows profile
here changed from `bpier` to `soluzka_3eenj0v`, all three venvs still pointed at
`C:\Users\bpier\AppData\…\Python311`, which no longer existed, and every service
failed to start until those paths were repointed. Recreate the environments on the
new machine rather than copying the folder.

## Troubleshooting

- **"database is locked"** — the connections use WAL and a 30 s busy timeout;
  the app and the exporter can both touch the database safely.
- **Genres missing on the live site** — run `tools/export_index.py`, confirm it
  prints `genres N/M`, then redeploy.
- **Download answers 405 or opens the source page** — `DOWNLOAD_API` is unset or
  unreachable; the page falls back to the original link.
- **Voice search does nothing** — the microphone needs a secure origin (https or
  localhost). On a LAN IP the browser blocks it.
- **The badge says "AI off"** — the song service is not running. Press **Start
  the AI**, or run `tools\start_services.ps1`; the badge turns green when
  `/health` answers.
- **The badge says `CUDA · warming 2m 30s` and keeps counting** — the model is
  still loading; fifty-one seconds is normal on this card, two minutes means
  something else is using the machine, four means look at `warm_failed` in
  `/health` and in `song_service\logs\service_err.log`.
- **The badge flips to "AI off" every time the page is reloaded, then comes
  back** — the service is answering too slowly for the probe. It is measured at
  twenty seconds in the launcher and twelve in the page; a host that misses both
  while loading is reported as `CUDA · busy loading` rather than lost.
- **A phone says "AI off" while the PC is fine** — the tunnel address is stale or
  the tunnel is down. `curl https://<worker>/api/song/endpoint` shows what the site
  holds; re-run the launcher to republish, then reload the page.
- **TikTok or Dailymotion will not play on a phone, but YouTube does** — the
  player needs `/pc/api/play` through the tunnel. Check
  `https://<tunnel>/pc/health` answers 200; if it does not, the tunnel is pointing
  somewhere else and a republish fixes it.
- **Nothing started after a boot** — compare `LastBootUpTime` with
  `build\launcher_trace.txt`. No line within a minute means the entry did not run:
  re-run `tools\install_autostart.ps1`. A line but no services means the head of
  `build\launcher_run.log` says why.
- **Start the AI does nothing** — `songsvc://` is not registered on this machine.
  Any run of `tools/start_services.ps1` registers it, including the Startup entry.
- **Lyrics take minutes instead of seconds** — the lyric model is running on the
  CPU. `/health` shows the device; unset `LYRICS_DEVICE` to let it pick CUDA.
- **A song takes about ten minutes** — 90 seconds of audio at 16 steps on one
  card. `ACE_STEPS` trades quality for time, `ACE_MAX_SECONDS` for length.
- **The tunnel answers 404 with no body** — cloudflared picked up
  `~/.cloudflared/config.yml`. Run the tunnel with
  `--config tools\bin\quick-tunnel.yml`, which the launcher already does.
- **"tunnel: could not fetch cloudflared"** — the first run needs GitHub
  reachable to download the 53 MB binary. It is retried on every launcher run;
  put `cloudflared.exe` in `tools\bin\` by hand if the machine is offline.
- **"tunnel: the download failed its signature check"** — something answered for
  GitHub that is not the signed release. The partial file is deleted; check the
  network or proxy rather than editing the check away.

`vercel.json` is a leftover deployment target that routes everything to
`app.py`; the Cloudflare Worker is the supported static deployment.
