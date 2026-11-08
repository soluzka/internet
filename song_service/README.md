# Song service

Two different things live near this folder, and it matters which is which.

## This service is the only song AI in the project

The deployed Worker runs one model, and it is not this one: Workers AI handles
voice search (`@cf/openai/whisper`). Nothing at the edge composes music — the
Workers AI catalog has no music model — so everything that writes words or sings
them happens here, on this machine.

The page calls `http://127.0.0.1:8090` for both halves of a song: the lyric model
first, then ACE-Step for the sung audio. That works from the deployed https page,
not just from localhost, because the service answers the browser's private
network preflight with `Access-Control-Allow-Private-Network`. When the service
is not running the page falls back to the sampled band in `public/index.html` —
instruments only, no voice.

## ACE-Step is the music model

This folder can also run a full model on your own GPU. That is **not** installed
to the website and cannot be: Workers have no Python, no CUDA and no gigabytes
of memory, and Cloudflare's containers are CPU-only, where a 3.5B diffusion
model is minutes to hours per song rather than seconds.

It is still useful locally, and it is free per song.

### Install

Everything is declared in `models.json`, so a fresh machine needs one command
and no manual cloning or pip archaeology. The file holds two lists:

| `packages` | Why it is there |
| --- | --- |
| `torch`, `torchaudio` (cu126 index) | the CUDA build; PyPI's default on Windows is CPU-only |
| `transformers==4.57.6`, `huggingface-hub==0.36.2` | the lyric model, pinned as a pair that works together |
| `git+https://github.com/ace-step/ACE-Step.git` | the music model's code |
| `flask`, `flask-cors` | the HTTP service the page calls |
| `soundfile`, `librosa` | writing the wav and ACE's audio loading |

| `models` | Size | Licence |
| --- | --- | --- |
| `ACE-Step/ACE-Step-v1-3.5B` — music, sings the lyrics | ≈7 GB | Apache-2.0 |
| `Qwen/Qwen2.5-1.5B-Instruct` — writes the lyrics | ≈3.1 GB | Apache-2.0 |

```
song_service\.venv\Scripts\python.exe install.py            # packages + both models
song_service\.venv\Scripts\python.exe install.py --packages   # code only
song_service\.venv\Scripts\python.exe install.py --weights    # models only
song_service\.venv\Scripts\python.exe install.py --check      # report, change nothing
song_service\.venv\Scripts\python.exe gpu_check.py            # confirms CUDA
```

`--check` is the quick answer to "is everything there?": it names each package,
each weight folder, and the installed torch/transformers versions, and exits
non-zero if anything is missing. Both models are fetched from Hugging Face into
`song_service/models/`, which is gitignored — they are package downloads, not
repository content.

One order matters: the lyrics model writes the words, then ACE-Step sings that
exact text, so both are needed for a sung song.

No CUDA toolkit install is needed on Windows: the driver supplies the runtime
and the torch wheel carries its own CUDA libraries. Check `models.json` →
`cuda` for the index and the minimum driver.

### Run

Start it with the launcher rather than by hand, because the launcher also warms
the model and keeps the site's Start the AI button registered:

```
powershell -NoProfile -ExecutionPolicy Bypass -File tools\start_services.ps1
```

By hand, from the repo root:

```
song_service\.venv\Scripts\python.exe song_service\app.py
```

Listens on `127.0.0.1:8090`:

```
GET  /health                                        -> device, card, vram, loaded
POST /api/lyrics {genre, subject, seed, ...}        -> {sections, lines, model}
POST /api/song   {prompt, lyrics, seconds, steps}   -> 202 {token}
GET  /api/song/<token>                              -> {status, progress, error}
GET  /api/song/latest                               -> the newest job, or {status: idle}
GET  /song_file/<token>                             -> the wav
GET  /last_song                                     -> the last render, after a restart
```

`/health` is the honest answer to "is it on the GPU":

```json
{"ok": true, "device": "cuda", "gpu": "NVIDIA GeForce RTX 4060 Ti",
 "vram_gb": 8.0, "loaded": true, "lyrics_loaded": true, "cpu_offload": true}
```

8 GB of VRAM is tight for a 3.5B model, so `ACE_CPU_OFFLOAD=1` is the default: it
pages weights in and out instead of running out of memory, at some cost in speed.

### Which model gets the card

Only one of the two fits. ACE-Step holds about 7.9 GB of the 8 GB card and Qwen
needs 3 GB, so whoever loads second pages — and paging was expensive: on this
machine a lyric request took **3m42s** that way.

The lyric model now loads only after the song model has been released, which
brings the same request to **10.5s**, and the song model is reloaded for the
render (~40s). `LYRICS_DEVICE=cpu` writes the words in system RAM instead, for a
machine whose card cannot be used at all.

`SONG_WARM=1` loads the song model at startup, so the first compose does not also
pay for the load. The launcher sets it; on its own the service answers health
immediately and loads on first use.

### Reaching this from the deployed page

Mixed content is not the obstacle it looks like: browsers treat loopback as
potentially trustworthy, so an `https://` page may call `http://127.0.0.1:8090`.
What Chrome adds is a private network preflight, and this service answers it in
an `after_request` hook with `Access-Control-Allow-Private-Network: true`, plus
the usual `Access-Control-Allow-Origin` and a 204 for the JSON preflight.

That is why the deployed page can render songs with no tunnel at all. The tunnel
in `start.ps1` is only for reaching the model from a *different* device, where
`127.0.0.1` means the phone rather than this machine.
