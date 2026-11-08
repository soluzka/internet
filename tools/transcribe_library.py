"""Transcribe the songs in the library so lyrics can come from what they say.

    .venv\\Scripts\\python tools\\transcribe_library.py --limit 5
    .venv\\Scripts\\python tools\\transcribe_library.py --query dubstep --limit 8

For each video it downloads the audio with yt-dlp, transcribes it with
faster-whisper (local, CPU, no service or key), and appends the text to
public/data/transcripts.json. The page reads that file and gives the lyric model
transcripts instead of titles.

Nothing is uploaded anywhere. Downloads and audio are temporary.
"""

import argparse
import datetime
import json
import os
import sys
import tempfile
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, 'public', 'data', 'videos.json')
OUT = os.path.join(ROOT, 'public', 'data', 'transcripts.json')

# Words that mean a listing has no usable text of its own.
JUNK = {'untitled', 'video', 'videos', 'youtube', 'unknown', 'official', 'audio'}


def load_index():
    with open(INDEX, encoding='utf-8') as handle:
        return json.load(handle)


def load_transcripts():
    if not os.path.exists(OUT):
        return {}
    try:
        with open(OUT, encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def save_transcripts(data):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    temporary = OUT + '.tmp'
    with open(temporary, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
    os.replace(temporary, OUT)


# Hosts yt-dlp can pull audio from. The index also contains plain web pages
# (Wikipedia articles and the like), which fail and waste a slot.
VIDEO_HOSTS = ('youtube.com', 'youtu.be', 'music.youtube.com', 'soundcloud.com',
               'vimeo.com', 'dailymotion.com')

# Titles that promise there is no voice to transcribe.
NO_VOCAL = ('instrumental', 'karaoke', 'no vocals', 'backing track', 'type beat',
            'ringtone', 'sound effect')


def is_video(url):
    lowered = str(url or '').lower()
    return any(host in lowered for host in VIDEO_HOSTS)


def pick_videos(index, query, limit, skip_instrumental=True):
    videos = index.get('videos', [])
    if query:
        words = [word for word in query.lower().split() if word]
        scored = []
        for video in videos:
            text = (video.get('t', '') + ' ' + video.get('d', '')).lower()
            score = sum(1 for word in words if word in text)
            if score:
                scored.append((score, video))
        scored.sort(key=lambda pair: -pair[0])
        videos = [video for _score, video in scored]
    picked = []
    for video in videos:
        if not is_video(video.get('u')):
            continue
        title = str(video.get('t', '')).lower()
        if skip_instrumental and any(word in title for word in NO_VOCAL):
            continue
        picked.append(video)
        if len(picked) >= limit:
            break
    return picked


def download_audio(url, workdir):
    import yt_dlp

    options = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(workdir, 'audio.%(ext)s'),
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 30,
        'retries': 2,
        'max_filesize': 90 * 1024 * 1024,
    }
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=True)
        if not info:
            raise RuntimeError('yt-dlp returned nothing')
        path = downloader.prepare_filename(info)
    for name in os.listdir(workdir):
        if name.startswith('audio'):
            return os.path.join(workdir, name)
    raise RuntimeError('no audio file was written')


def transcribe(path, model, max_seconds):
    segments, info = model.transcribe(path, vad_filter=True, beam_size=1)
    parts = []
    last = 0.0
    for segment in segments:
        parts.append(segment.text.strip())
        last = segment.end
        if max_seconds and last > max_seconds:
            break
    return ' '.join(part for part in parts if part), last


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=3, help='how many videos')
    parser.add_argument('--query', default='', help='only videos matching these words')
    parser.add_argument('--model', default='base', help='faster-whisper model size')
    parser.add_argument('--max-seconds', type=float, default=180.0, help='audio length cap')
    args = parser.parse_args()

    index = load_index()
    videos = pick_videos(index, args.query, args.limit)
    if not videos:
        raise SystemExit('no videos matched')

    from faster_whisper import WhisperModel

    print(f'loading whisper "{args.model}" on CPU...', flush=True)
    model = WhisperModel(args.model, device='cpu', compute_type='int8')

    transcripts = load_transcripts()
    done = 0
    for video in videos:
        url = video['u']
        if url in transcripts:
            print(f'skip (already done): {video.get("t", "")[:60]}', flush=True)
            continue
        workdir = tempfile.mkdtemp(prefix='transcribe_')
        print(f'\n== {video.get("t", "")[:70]}', flush=True)
        try:
            path = download_audio(url, workdir)
            text, seconds = transcribe(path, model, args.max_seconds)
            if not text.strip():
                # Nothing sung (a beat, a sample pack, silence). Remember it so a
                # later run does not spend minutes downloading it again.
                transcripts[url] = {'t': '', 'empty': True, 's': round(seconds, 1),
                                    'at': datetime.datetime.now(
                                        datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
                save_transcripts(transcripts)
                print('   no vocals in this one, recorded as empty', flush=True)
                continue
            transcripts[url] = {
                't': text[:4000],
                's': round(seconds, 1),
                'at': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            }
            save_transcripts(transcripts)
            done += 1
            print(f'   {len(text.split())} words, {seconds:.0f}s of audio', flush=True)
            print('   ' + text[:180].replace('\n', ' '), flush=True)
        except Exception as exc:  # noqa: BLE001 - one bad video must not stop the run
            print(f'   failed: {exc}', flush=True)
            traceback.print_exc(limit=1)
        finally:
            import shutil

            shutil.rmtree(workdir, ignore_errors=True)

    print(f'\nfinished: {done} new transcript(s) in {OUT}', flush=True)
    if done == 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
