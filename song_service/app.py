"""Local song service: ACE-Step, running on this machine's GPU.

The public page is static and cannot host a 3.5B model, so the model lives
here. The service loads it once, takes one job at a time (a single GPU cannot
usefully run two), and reports progress while it works.

    GET  /health                 -> {"ok": true, "model": ..., "device": ...}
    POST /api/song   {prompt, lyrics, seconds, steps}  -> 202 {"token", "status"}
    GET  /api/song/<token>       -> {"status", "elapsed", "progress", "error"}
    GET  /api/song/latest        -> the newest job, so a reloaded page can join it
    GET  /song_file/<token>      -> the rendered wav, kept for the panel's links
    GET  /last_song              -> logs/last_song.wav, whatever was rendered last

Nothing here is downloaded from a third party at request time: the checkpoint
sits in ACE_CHECKPOINT and the weights were fetched once during setup.
"""

import gc
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import traceback
import uuid

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# The vendored ACE-Step checkout and its weights.
ACE_REPO = os.environ.get('ACE_REPO', os.path.join(ROOT, 'third_party', 'ACE-Step'))
CHECKPOINT = os.environ.get('ACE_CHECKPOINT', os.path.join(HERE, 'models', 'ACE-Step-v1-3.5B'))

if ACE_REPO not in sys.path:
    sys.path.insert(0, ACE_REPO)

app = Flask(__name__)

# The page is served from another origin, so every route answers CORS.
CORS(app, resources={r"/*": {
    "origins": "*",
    "methods": ["GET", "POST", "OPTIONS"],
    "allow_headers": ["Content-Type"],
    "expose_headers": ["Content-Disposition"],
    "max_age": 86400,
}})

@app.after_request
def _allow_private_network(response):
    # The deployed page is served over https and calls this service on
    # http://127.0.0.1:8090, so the browser asks before a public page may reach a
    # loopback address. Answering the preflight keeps that request from being
    # blocked, which is what makes the model work without a tunnel.
    if request.headers.get('Access-Control-Request-Private-Network'):
        response.headers['Access-Control-Allow-Private-Network'] = 'true'
    return response


# 8 GB of VRAM cannot hold the whole 3.5B model alongside the decoder, so the
# weights are paged in and out instead of failing with an out-of-memory error.
CPU_OFFLOAD = os.environ.get('ACE_CPU_OFFLOAD', '1') != '0'
DTYPE = os.environ.get('ACE_DTYPE', 'bfloat16')
DEFAULT_STEPS = int(os.environ.get('ACE_STEPS', '30'))
MAX_SECONDS = float(os.environ.get('ACE_MAX_SECONDS', '120'))

_pipeline = None
_pipeline_lock = threading.Lock()
_gpu_lock = threading.Lock()      # one generation at a time
_jobs = {}
_jobs_lock = threading.Lock()
_latest_token = None   # the song the page asked for most recently


_lyricist_instance = None
_lyricist_lock = threading.Lock()


def _release_pipeline():
    """Drop the song model so the card is free for the lyric model.

    ACE-Step holds about 7.9 GB of the 8 GB card and Qwen needs 3 GB, so the two
    cannot sit there together: whoever goes second pages, and paging cost a
    minute on the lyrics and doubled the render to 23 s a step. Every compose
    starts with the lyrics, so the lyric model takes the card and the song model
    is loaded again afterwards - about 40 seconds, which is cheaper than the
    paging it replaces and much cheaper than six megabytes of Qwen per second.
    """
    global _pipeline
    with _pipeline_lock:
        instance = _pipeline
        _pipeline = None
    if instance is not None:
        del instance
        import gc

        gc.collect()
        try:
            import torch

            torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass
        print('released the song model to free VRAM', flush=True)


def _lyricist():
    """One language model for the process, loaded on first use.

    On a GPU it is loaded only after the song model has been released, so it
    arrives on an empty card in about ten seconds instead of paging into the few
    hundred megabytes ACE-Step leaves behind. LYRICS_DEVICE=cpu writes the words
    in system RAM instead, which costs more time but never touches the card.
    """
    global _lyricist_instance
    with _lyricist_lock:
        if _lyricist_instance is None:
            from lyrics import Lyricist, lyrics_model_id, load_manifest

            device = os.environ.get('LYRICS_DEVICE')
            if not device:
                try:
                    import torch

                    device = 'cuda' if torch.cuda.is_available() else 'cpu'
                except Exception:  # noqa: BLE001
                    device = 'cpu'
            if device.startswith('cuda'):
                _release_pipeline()
            _lyricist_instance = Lyricist(lyrics_model_id(load_manifest()), device=device)
        return _lyricist_instance


def _load_pipeline():
    """Load the model once; the first call takes a minute or two."""
    global _pipeline
    with _pipeline_lock:
        if _pipeline is not None:
            return _pipeline
        if not os.path.isdir(CHECKPOINT):
            raise RuntimeError(f'Checkpoint not found: {CHECKPOINT}')
        from acestep.pipeline_ace_step import ACEStepPipeline
        _pipeline = ACEStepPipeline(
            checkpoint_dir=CHECKPOINT,
            dtype=DTYPE,
            torch_compile=False,
            cpu_offload=CPU_OFFLOAD,
        )
        return _pipeline


def _prune_jobs():
    """Forget all but the newest finished jobs, with their temp audio.

    The page streams a finished song twice - once into the player and again
    from "Save the song" - so the file cannot be deleted on the first read.
    Keeping a couple of renders is a few megabytes; keeping every one is not.

    """
    with _jobs_lock:
        done = [token for token, job in _jobs.items()
                if job['status'] in ('complete', 'error') and token != _latest_token]
        for token in done[:-1]:
            job = _jobs.pop(token, None)
            if job:
                shutil.rmtree(job.get('tmp_dir') or '', ignore_errors=True)


def _set(token, **fields):
    with _jobs_lock:
        job = _jobs.get(token)
        if job is not None:
            job.update(fields)


def _prompt_for(genres, words, bpm, key):
    """A tag prompt in the shape the model expects: genre, mood, instruments."""
    parts = [', '.join(genres[:3]) if genres else 'electronic']
    if bpm:
        parts.append(f'{bpm} bpm')
    if key:
        parts.append(key)
    if words:
        parts.append('samples of ' + ', '.join(words[:4]))
    parts.append('mastered, wide stereo, emotional vocal')
    return ', '.join(parts)


def _warm_lyrics():
    """Load the lyric model at startup, not on the first click.

    Loading takes tens of seconds. Doing it here means the page's first lyric
    request comes back quickly instead of spending that time on "Composing...".
    The model is released again before a song job loads ACE-Step, so the two
    still never share the 8 GB of VRAM.
    """
    try:
        _lyricist()
        print('lyric model ready', flush=True)
    except Exception:  # noqa: BLE001 - a failed warm-up must not stop the service
        traceback.print_exc()


threading.Thread(target=_warm_lyrics, daemon=True).start()


def _release_lyricist():
    """Give the lyric model's memory back before the 3.5B music model loads.

    It lives in system RAM now, not VRAM, but ACE-Step pages its 7.9 GB of
    weights through RAM too, so the 6 GB Qwen holds is still worth freeing
    before every render.
    """
    global _lyricist_instance
    with _lyricist_lock:
        instance = _lyricist_instance
        _lyricist_instance = None
    if instance is None:
        return
    try:
        instance._pipeline = None
    except Exception:  # noqa: BLE001 - best effort, it is being thrown away
        pass
    del instance
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass
    print('released the lyric model to free VRAM', flush=True)


def _write_samples(target_wav, out_path, sample_rate):
    """Write a decoded waveform without depending on libsndfile.

    ACE-Step saves through torchaudio, and torchaudio 2.9 dropped its soundfile
    and sox backends: every save now goes through torchcodec, which is not
    installed, so generation ended in "TorchCodec is required for
    save_with_torchcodec" after the whole expensive diffusion had run. Writing
    the samples ourselves costs nothing and needs no extra package.
    """
    import numpy as np

    samples = target_wav
    if hasattr(samples, 'detach'):
        samples = samples.detach().float().cpu().numpy()
    if isinstance(samples, (list, tuple)):
        samples = samples[0] if samples else None
        if samples is None:
            raise RuntimeError('the model returned no waveform')
        if hasattr(samples, 'detach'):
            samples = samples.detach().float().cpu().numpy()
    samples = np.asarray(samples, dtype=np.float32).squeeze()
    if samples.ndim == 0 or samples.size == 0:
        raise RuntimeError('the model returned an empty waveform')
    print(f'waveform: shape={samples.shape} peak={float(np.abs(samples).max()):.3f}', flush=True)

    # The decoder hands over (channels, frames). Getting this wrong writes two
    # samples and produces a 48-byte "song" - silent, no vocal, which is exactly
    # what happened before.
    if samples.ndim == 1:
        frames = samples[:, None]
    elif samples.shape[0] <= 4 and samples.shape[1] > samples.shape[0]:
        frames = samples.T
    else:
        frames = samples
    channels = frames.shape[1]

    # Stdlib writer first: libsndfile in this environment refuses the file with
    # "Format not recognised" even when the format is given explicitly, and the
    # wave module cannot fail that way.
    import wave

    # Every render is lifted to the same peak. The model hands back whatever
    # level it feels like - some songs peaked at 0.4 and sounded muffled next to
    # the loud browser band - so 0.95 (about -0.5 dBFS) is applied here instead
    # of only trimming the ones that clip.
    peak = float(np.abs(frames).max())
    scale = (0.95 / peak) if peak > 1e-6 else 1.0
    pcm = np.clip(frames * scale, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype('<i2')
    with wave.open(out_path, 'wb') as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(int(sample_rate))
        handle.writeframes(pcm.tobytes())
    print(f'wrote {out_path}: {channels} ch, {frames.shape[0]} frames', flush=True)
    return out_path

    # Explicit format: letting libsndfile infer it from the file name failed
    # inside this process with "Format not recognised", so it is stated here.
    
def _use_soundfile_writes(pipeline):
    """Replace the pipeline's torchaudio save with a soundfile save.

    The pipeline writes its wav inside __call__ and returns the paths it wrote,
    so the writing step itself has to be replaced - there is no flag for it.
    The signature and the returned path are kept, so the rest of __call__
    (including the input-params json written next to the audio) still works.
    """
    cls = type(pipeline)
    if getattr(cls, '_writes_with_soundfile', False):
        return pipeline

    def save_wav_file(self, target_wav, idx, save_path=None, sample_rate=48000, format='wav'):
        if save_path is None:
            base = os.path.join(os.getcwd(), 'outputs')
            os.makedirs(base, exist_ok=True)
            path = os.path.join(base, f'output_{time.strftime("%Y%m%d%H%M%S")}_{idx}.wav')
        elif os.path.isdir(save_path):
            path = os.path.join(save_path, f'output_{time.strftime("%Y%m%d%H%M%S")}_{idx}.wav')
        else:
            parent = os.path.dirname(save_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            path = save_path
        print(f'saving audio to {path} with soundfile', flush=True)
        return _write_samples(target_wav, path, sample_rate)

    cls.save_wav_file = save_wav_file
    cls._writes_with_soundfile = True
    print('ACE-Step will write wav files with soundfile (no torchcodec)', flush=True)
    return pipeline


def _run_job(token, prompt, lyrics, seconds, steps, seed):
    tmp_dir = tempfile.mkdtemp(prefix='ace_')
    out_path = os.path.join(tmp_dir, 'song.wav')
    started = time.time()
    _set(token, status='loading', progress=0.02, tmp_dir=tmp_dir)
    try:
        _release_lyricist()
        pipeline = _use_soundfile_writes(_load_pipeline())
        _set(token, status='generating', progress=0.1)
        with _gpu_lock:
            outputs = pipeline(
                audio_duration=seconds,
                prompt=prompt,
                lyrics=lyrics,
                infer_step=steps,
                guidance_scale=15.0,
                scheduler_type='euler',
                cfg_type='apg',
                omega_scale=10.0,
                manual_seeds=[seed],
                guidance_interval=0.5,
                guidance_interval_decay=0.0,
                min_guidance_scale=3.0,
                use_erg_tag=True,
                use_erg_lyric=True,
                use_erg_diffusion=True,
                oss_steps=[],
                guidance_scale_text=0.0,
                guidance_scale_lyric=0.0,
                save_path=out_path,
            )
        print(f'pipeline returned {len(outputs or [])} item(s)', flush=True)
        if not os.path.exists(out_path):
            # Newer/older checkouts name the file themselves; take whatever wav
            # the pipeline reported or wrote.
            for item in outputs or []:
                if isinstance(item, str) and item.endswith('.wav') and os.path.exists(item):
                    out_path = item
                    break
        if not os.path.exists(out_path):
            for name in os.listdir(tmp_dir):
                if name.endswith('.wav'):
                    out_path = os.path.join(tmp_dir, name)
                    break
        if not os.path.exists(out_path):
            raise RuntimeError('The model finished without writing a wav file')
        # Keep the last render next to the logs: the job's own copy is deleted as
        # soon as the page has streamed it, and without a copy there is no way to
        # check afterwards whether the voice is really in the audio.
        try:
            logs = os.path.join(HERE, 'logs')
            os.makedirs(logs, exist_ok=True)
            shutil.copyfile(out_path, os.path.join(logs, 'last_song.wav'))
            print('kept a copy at logs/last_song.wav', flush=True)
        except OSError as exc:
            print(f'could not keep a copy of the render: {exc}', flush=True)
        _set(token, status='complete', progress=1.0, path=out_path,
             elapsed=round(time.time() - started, 1))
    except Exception as exc:  # noqa: BLE001 - reported to the page as text
        traceback.print_exc()
        _set(token, status='error', error=str(exc)[:400],
             elapsed=round(time.time() - started, 1))


@app.route('/api/lyrics', methods=['POST', 'OPTIONS'])
def api_lyrics():
    """Write lyrics for the page with the local language model."""
    if request.method == 'OPTIONS':
        return ('', 204)
    body = request.get_json(silent=True) or {}
    genre = str(body.get('genre') or 'electronic music')[:120]
    subject = str(body.get('subject') or '')[:400]
    seed = int(body.get('seed') or 0)
    corpus = body.get('corpus') or []
    if not isinstance(corpus, list):
        corpus = []
    corpus = [str(item)[:80] for item in corpus][:60]
    angle = str(body.get('angle') or '')[:120]
    avoid = body.get('avoid') or []
    if not isinstance(avoid, list):
        avoid = []
    avoid = [str(line)[:160] for line in avoid][-14:]

    try:
        from lyrics import Lyricist, lyrics_model_id, load_manifest

        lyricist = _lyricist()
        # A whole song in sections: verses, a chorus that repeats, a bridge.
        song = lyricist.write_song(genre, subject, seed, corpus=corpus, angle=angle, avoid=avoid)
        sections = song.get('sections') or []
        lines = song.get('lines') or []
    except Exception as exc:  # noqa: BLE001 - report the reason to the page
        traceback.print_exc()
        return jsonify({'error': f'lyric model failed: {exc}'}), 500

    print('wrote %d sections / %d lines' % (len(sections), len(lines)), flush=True)
    if len(lines) < 6 or len(sections) < 2:
        return jsonify({'error': 'lyric model returned too little text',
                        'lines': lines, 'sections': sections}), 502
    return jsonify({'lines': lines, 'sections': sections,
                    'model': lyrics_model_id(load_manifest())})


def _gpu():
    """What the render will run on, so /health can say cuda instead of guessing."""
    try:
        import torch

        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            return {'device': 'cuda', 'gpu': torch.cuda.get_device_name(0),
                    'vram_gb': round(props.total_memory / (1024 ** 3), 1)}
    except Exception:  # noqa: BLE001
        pass
    return {'device': 'cpu', 'gpu': None, 'vram_gb': None}


@app.route('/health')
def health():
    ready = _pipeline is not None
    return jsonify({
        'ok': True,
        'model': 'ACE-Step v1 3.5B',
        'checkpoint': CHECKPOINT,
        'checkpoint_present': os.path.isdir(CHECKPOINT),
        'loaded': ready,
        'cpu_offload': CPU_OFFLOAD,
        'dtype': DTYPE,
        'lyrics_loaded': _lyricist_instance is not None,
        **_gpu(),
    })


@app.route('/api/song', methods=['POST', 'OPTIONS'])
def api_song():
    if request.method == 'OPTIONS':
        return ('', 204)

    data = request.get_json(silent=True) or {}
    prompt = (data.get('prompt') or '').strip()
    lyrics = (data.get('lyrics') or '').strip()
    if not lyrics:
        return jsonify({'error': 'No lyrics provided'}), 400
    if not prompt:
        prompt = 'electronic, instrumental, cinematic'

    try:
        seconds = float(data.get('seconds') or 60)
    except (TypeError, ValueError):
        seconds = 60
    seconds = max(8.0, min(MAX_SECONDS, seconds))

    try:
        steps = int(data.get('steps') or DEFAULT_STEPS)
    except (TypeError, ValueError):
        steps = DEFAULT_STEPS
    steps = max(8, min(80, steps))

    global _latest_token
    token = uuid.uuid4().hex
    seed = int(data.get('seed') or (uuid.uuid4().int % 1000000))
    with _jobs_lock:
        # One GPU, one song. A second click while a song is still rendering - or
        # a page that was reloaded and asked again - joins the song in flight
        # instead of queueing another multi-minute render behind it.
        for running_token, job in _jobs.items():
            if job['status'] in ('queued', 'loading', 'generating'):
                return jsonify({'token': running_token, 'status': job['status'],
                                'seconds': job['seconds'], 'reused': True}), 202

    # Outside the lock: _prune_jobs takes it itself.
    _prune_jobs()
    with _jobs_lock:
        _jobs[token] = {
            'status': 'queued', 'progress': 0.0, 'error': '',
            'path': None, 'tmp_dir': None, 'elapsed': 0,
            'prompt': prompt, 'seconds': seconds,
            'created': time.time(),
        }
        _latest_token = token

    threading.Thread(target=_run_job, args=(token, prompt, lyrics, seconds, steps, seed),
                     daemon=True).start()
    return jsonify({'token': token, 'status': 'queued', 'prompt': prompt,
                    'seconds': seconds, 'steps': steps}), 202


@app.route('/api/song/latest')
def api_song_latest():
    """The newest job, so a reloaded or restarted page can join the song.

    A song takes minutes on one card. Without this the token only existed in
    the page's memory: a reload, a closed tab or a restarted app left the model
    singing into nothing, and the page looked like it had never run it.

    """
    with _jobs_lock:
        job = _jobs.get(_latest_token) if _latest_token else None
        if job is None:
            # Nothing has been asked for since this process started. That is a
            # normal state, not a missing resource: a 404 made the page's console
            # read as if something had gone wrong.
            return jsonify({'status': 'idle', 'token': None})
        return jsonify({
            'token': _latest_token,
            'status': job['status'],
            'progress': job['progress'],
            'error': job['error'],
            'elapsed': round(time.time() - job['created'], 1),
            'seconds': job['seconds'],
        })


@app.route('/api/song/<token>')
def api_song_status(token):
    with _jobs_lock:
        job = _jobs.get(token)
        if job is None:
            return jsonify({'error': 'Unknown or expired job'}), 404
        return jsonify({
            'status': job['status'],
            'progress': job['progress'],
            'error': job['error'],
            'elapsed': round(time.time() - job['created'], 1),
            'seconds': job['seconds'],
        })


@app.route('/song_file/<token>')
def song_file(token):
    with _jobs_lock:
        job = _jobs.get(token)
        if job is None or job['status'] != 'complete' or not job.get('path'):
            return jsonify({'error': 'File not found or not finished'}), 404
        path = job['path']
        prompt = job['prompt'] or 'song'

    if not os.path.exists(path):
        return jsonify({'error': 'File not found or expired'}), 404

    label = re.sub(r'[^a-z0-9]+', '-', prompt.lower())[:40].strip('-') or 'song'
    # The job stays until a later one replaces it: the page reads this file once
    # for the player and again when "Save the song" is clicked, and a reloaded
    # page may ask for it a third time.
    return send_file(path, as_attachment=True,
                     download_name=f'library-song-{label}.wav',
                     mimetype='audio/wav')


@app.route('/last_song')
def last_song():
    """The last rendered song, saved next to the logs.

    A stable address for the one thing that matters after a restart: the audio
    the model actually produced.
    """
    path = os.path.join(HERE, 'logs', 'last_song.wav')
    if not os.path.exists(path):
        return jsonify({'error': 'Nothing has been rendered yet'}), 404
    return send_file(path, as_attachment=True, download_name='last-song.wav',
                     mimetype='audio/wav')


def _warm():
    """Put the song model on the card at startup instead of on the first song.

    Everything else loading lazily keeps the service quick to answer, but the
    first compose then pays for the load. With SONG_WARM=1 that minute is spent
    quietly after start instead, and health reports loaded: true when it is
    ready. Off by default, because holding 8 GB of VRAM from the moment a
    service starts is not what every machine wants.
    """
    try:
        info = _gpu()
        print(f'warming on {info["device"]}: {info.get("gpu") or "cpu"}', flush=True)
        _load_pipeline()
        print('song model ready', flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f'warm load failed: {exc}', flush=True)


if __name__ == '__main__':
    # The page looks for this service on 8090, so an empty or zero PORT from the
    # environment must not turn into a random port.
    port = int(os.environ.get('SONG_PORT') or os.environ.get('PORT') or 8090)
    if not port:
        port = 8090
    if os.environ.get('SONG_WARM', '0') not in ('0', '', 'false', 'False'):
        threading.Thread(target=_warm, daemon=True).start()
    # Otherwise loading happens on the first request so the service answers
    # health immediately.
    app.run(host='127.0.0.1', port=port, threaded=True)
