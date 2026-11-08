"""Local song service: ACE-Step, running on this machine's GPU.

The public page is static and cannot host a 3.5B model, so the model lives
here. The service loads it once, takes one job at a time (a single GPU cannot
usefully run two), and reports progress while it works.

    GET  /health                 -> {"ok": true, "model": ..., "device": ...}
    POST /api/song   {prompt, lyrics, seconds, steps}  -> 202 {"token", "status"}
    GET  /api/song/<token>       -> {"status", "elapsed", "progress", "error"}
    GET  /song_file/<token>      -> the rendered wav, then the job is deleted

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


_lyricist_instance = None
_lyricist_lock = threading.Lock()


def _lyricist():
    """One language model for the process, loaded on first use."""
    global _lyricist_instance
    with _lyricist_lock:
        if _lyricist_instance is None:
            from lyrics import Lyricist, lyrics_model_id, load_manifest

            _lyricist_instance = Lyricist(lyrics_model_id(load_manifest()))
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


def _release_lyricist():
    """Give the lyric model's VRAM back before the 3.5B music model loads.

    Both cannot sit in 8 GB at once: Qwen takes about 3 GB, ACE-Step about 7.9,
    and trying to hold both is what wedged the service.
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


def _run_job(token, prompt, lyrics, seconds, steps, seed):
    tmp_dir = tempfile.mkdtemp(prefix='ace_')
    out_path = os.path.join(tmp_dir, 'song.wav')
    started = time.time()
    _set(token, status='loading', progress=0.02, tmp_dir=tmp_dir)
    try:
        _release_lyricist()
        pipeline = _load_pipeline()
        _set(token, status='generating', progress=0.1)
        with _gpu_lock:
            pipeline(
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
        if not os.path.exists(out_path):
            # Some versions write next to the working directory instead.
            for name in os.listdir(tmp_dir):
                if name.endswith('.wav'):
                    out_path = os.path.join(tmp_dir, name)
                    break
        if not os.path.exists(out_path):
            raise RuntimeError('The model finished without writing a wav file')
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

    try:
        from lyrics import Lyricist, lyrics_model_id, load_manifest

        lyricist = _lyricist()
        lines = lyricist.write(genre, subject, seed, corpus=corpus)
    except Exception as exc:  # noqa: BLE001 - report the reason to the page
        traceback.print_exc()
        return jsonify({'error': f'lyric model failed: {exc}'}), 500

    if len(lines) < 6:
        return jsonify({'error': 'lyric model returned too little text', 'lines': lines}), 502
    return jsonify({'lines': lines, 'model': lyrics_model_id(load_manifest())})


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

    with _jobs_lock:
        running = sum(1 for job in _jobs.values()
                      if job['status'] in ('loading', 'generating'))
    if running >= 2:
        return jsonify({'error': 'The GPU is busy with another song. Try again in a moment.'}), 429

    token = uuid.uuid4().hex
    seed = int(data.get('seed') or (uuid.uuid4().int % 1000000))
    with _jobs_lock:
        _jobs[token] = {
            'status': 'queued', 'progress': 0.0, 'error': '',
            'path': None, 'tmp_dir': None, 'elapsed': 0,
            'prompt': prompt, 'seconds': seconds,
            'created': time.time(),
        }

    threading.Thread(target=_run_job, args=(token, prompt, lyrics, seconds, steps, seed),
                     daemon=True).start()
    return jsonify({'token': token, 'status': 'queued', 'prompt': prompt,
                    'seconds': seconds, 'steps': steps}), 202


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
    response = send_file(path, as_attachment=True,
                         download_name=f'library-song-{label}.wav',
                         mimetype='audio/wav')

    @response.call_on_close
    def cleanup():
        with _jobs_lock:
            finished = _jobs.pop(token, None)
        if finished:
            shutil.rmtree(finished.get('tmp_dir') or '', ignore_errors=True)

    return response


if __name__ == '__main__':
    # The page looks for this service on 8090, so an empty or zero PORT from the
    # environment must not turn into a random port.
    port = int(os.environ.get('SONG_PORT') or os.environ.get('PORT') or 8090)
    if not port:
        port = 8090
    # Loading happens on the first request so the service reports health quickly.
    app.run(host='127.0.0.1', port=port, threaded=True)
