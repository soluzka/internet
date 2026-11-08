# Song service

Two different things live near this folder, and it matters which is which.

## This service is the only AI in the project

The deployed Worker runs no models: `worker.js` serves the static page and
proxies downloads, and `wrangler.jsonc` declares no AI binding. Everything that
writes or sings happens here, on this machine.

When the page is opened locally it calls `http://127.0.0.1:8090` for both halves
of a song: the lyric model first, then ACE-Step for the sung audio. If this
service is not running, the page falls back to the sampled band in
`public/index.html` — instruments only, no voice.

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
