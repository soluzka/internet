"""Does this audio actually contain a sung voice? Transcribe it and print.

    .venv\\Scripts\\python tools\\check_vocals.py song_service/logs/last_song.wav

Whisper hears speech and singing. If the model's wav has a vocal, words come
back; if it is instrumental, the transcript is empty. That is a plain test for
"did it sing", instead of guessing by ear.
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT = os.path.join(ROOT, 'song_service', 'logs', 'last_song.wav')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio', nargs='?', default=DEFAULT)
    parser.add_argument('--model', default='base')
    args = parser.parse_args()

    path = args.audio
    if not os.path.exists(path):
        raise SystemExit(f'no such file: {path}')
    size = os.path.getsize(path)
    print(f'{path} ({size / 1024 / 1024:.2f} MB)', flush=True)
    if size < 2000:
        raise SystemExit('that file is too small to be audio (probably an error page)')

    from faster_whisper import WhisperModel

    model = WhisperModel(args.model, device='cpu', compute_type='int8')
    segments, info = model.transcribe(path, vad_filter=True, beam_size=1)
    words = 0
    print(f'language {info.language} ({info.language_probability:.2f})', flush=True)
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        words += len(text.split())
        print(f'  [{segment.start:6.1f} - {segment.end:6.1f}] {text}', flush=True)
    print(f'\n{words} transcribed words')
    if words < 3:
        print('NO VOCAL: nothing singable was heard in this render')
        sys.exit(1)
    print('VOCAL PRESENT: the model sang words over the music')


if __name__ == '__main__':
    main()
