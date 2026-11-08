# Song service

Two different things live near this folder, and it matters which is which.

## The website uses Cloudflare's model

`worker.js` routes `POST /api/song` and `GET /api/song-file` to the model that
Cloudflare hosts:

```
env.AI.run('minimax/music-2.6', { prompt, lyrics, is_instrumental: false })
```

That gives a real song with sung vocals from the page, on any device, with no
local machine, no tunnel and no download. It bills roughly $0.15 per track, so
the page only calls it when you press the button. `song-file` proxies the
provider's audio so the page receives one same-origin file.

When that route does not exist (plain static hosting, or a local Flask run with
no Worker in front), the page falls back to the browser synthesiser in
`public/index.html` — free and instant, but it sounds like a synth, because it
is one.

## ACE-Step here is the local alternative

This folder can also run a full model on your own GPU. That is **not** installed
to the website and cannot be: Workers have no Python, no CUDA and no gigabytes
of memory, and Cloudflare's containers are CPU-only, where a 3.5B diffusion
model is minutes to hours per song rather than seconds.

It is still useful locally, and it is free per song.

### Install

Everything is declared in `models.json`: the packages (each with the wheel index
that makes PyTorch a CUDA build rather than the CPU one) and the weights repo.

```
song_service\.venv\Scripts\python.exe install.py            # packages + weights
song_service\.venv\Scripts\python.exe install.py --packages
song_service\.venv\Scripts\python.exe install.py --weights
song_service\.venv\Scripts\python.exe gpu_check.py          # confirms CUDA
```

No CUDA toolkit install is needed on Windows: the driver supplies the runtime
and the torch wheel carries its own CUDA libraries. Check `models.json` →
`cuda` for the index and the minimum driver.

### Run

```
song_service\.venv\Scripts\python.exe song_service\app.py
```

Listens on `127.0.0.1:8090`:

```
GET  /health
POST /api/song   {prompt, lyrics, seconds, steps}  -> 202 {token}
GET  /api/song/<token>                              -> {status, progress, error}
GET  /song_file/<token>                             -> the wav
```

8 GB of VRAM is tight for a 3.5B model, so `ACE_CPU_OFFLOAD=1` is the default: it
pages weights in and out instead of running out of memory, at some cost in speed.

### Why the page does not call this

A deployed site is `https://`, and a browser blocks `http://127.0.0.1:8090` from
it as mixed content. Reaching the local model would need a tunnel or a page
served over plain http — which is exactly the setup the hosted model avoids.
