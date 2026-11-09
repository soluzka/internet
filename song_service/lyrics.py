"""Write song lyrics with a small language model, on this machine.

The page asks for lyrics before it asks for music, so this runs on the GPU (or
CPU if CUDA is unavailable).

    song_service\\.venv\\Scripts\\python lyrics.py --genre techno

The model is a songwriter, not a word shuffler: it is asked for a whole song in
sections, it must repeat its chorus word for word, and it is told to write its
own lines rather than pasting the phrases it was given. The phrases from the
videos are only there to suggest a theme.
"""

import argparse
import json
import os
import random
import re
import sys
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))

SYSTEM_PROMPT = (
    'You are a songwriter and lyricist with a voice of your own. You write '
    'complete, singable song lyrics that could be recorded today. You never '
    'explain yourself, never describe the process, and never mention where your '
    'ideas came from. You answer with the lyric only.'
)

SONG_PROMPT = (
    'Write the complete lyric of a new {genre} song.\n'
    '\n'
    'You choose what it is about. Pick one situation and let the whole song '
    'live in it.{theme_hint}\n'
    'The singer: {angle}\n'
    'Mood: {mood}\n'
    '\n'
    'Use exactly this shape. Each tag sits on its own line, then its lines:\n'
    '[verse 1]\n'
    '[chorus]\n'
    '[verse 2]\n'
    '[chorus]\n'
    '[verse 3]\n'
    '[bridge]\n'
    '[chorus]\n'
    '\n'
    'How to write it:\n'
    '- Choose one idea for this song - one place, one night, one thing that '
    'happened - and stay with it from the first line to the last.\n'
    '- The chorus is the same words every time it appears, word for word. It is '
    'the part someone would sing back.\n'
    '- The verses move: in verse one something is happening, in verse two '
    'something has changed, and verse three is what it costs. The bridge says '
    'the thing the verses avoided.\n'
    '- Your own language, your own images. Nobody has given you words to reuse: '
    'invent the details - a name, an object, a place, a time - that only this '
    'song has.\n'
    '- Concrete things a person can see, do or lose. No metaphors about music, '
    'technology, the internet or collections of anything.\n'
    '- Four lines per verse, four per chorus, two for the bridge: a minute and '
    'a half of singing needs that much. Under twelve words a line. Do not force '
    'rhymes.\n'
    '- Singable rhythm: short lines, plain words, one thought per line.\n'
    '- No title, no numbering, no notes, no quotation marks. Only the tags and '
    'the lines.\n'
    '{avoid}'
)

TAG = re.compile(r'^\s*[\[\(]\s*(verse\s*\d|chorus|hook|bridge|pre[-\s]?chorus|'
                 r'intro|outro|refrain)\s*[\]\)]\s*:?\s*$', re.I)

# Lines that describe the collection instead of a life are thrown away rather
# than shown as lyrics.
BANNED = re.compile(
    r'\b(libraries|library|database|databases|collection|playlist|playlists|'
    r'search\w*|index|indexed|algorithm|metadata|catalog\w*|archiv\w+|'
    r'tracks?|videos?|clips?|uploads?|channels?|subscri\w+|results?)\b',
    re.I,
)

MOODS = [
    'tired and honest, played late',
    'warm but restless',
    'cold air, steady nerve',
    'hopeful underneath',
    'sharp and plainspoken',
    'quiet, then loud',
]


def load_manifest():
    with open(os.path.join(ROOT, 'models.json'), encoding='utf-8') as handle:
        return json.load(handle)


def lyrics_model_id(manifest):
    """The downloaded weights when they exist, otherwise the repo to fetch."""
    for model in manifest.get('models') or []:
        if model.get('kind') != 'lyrics':
            continue
        local = os.path.normpath(os.path.join(os.path.dirname(ROOT), model.get('target', '')))
        if model.get('target') and os.path.isdir(local) and any(os.scandir(local)):
            return local
        return model.get('repo', 'Qwen/Qwen2.5-1.5B-Instruct')
    return 'Qwen/Qwen2.5-1.5B-Instruct'


def _text_pipeline(wait_seconds=180):
    """`transformers.pipeline`, waiting out an import another thread started.

    The warm-up imports transformers for the song model and for this one, and a
    module that is still initialising is in sys.modules without its attributes
    yet - so `from transformers import pipeline` raises ImportError there instead
    of waiting. That is what the first lyric request of a session hit on 8 Nov
    2026: a 500 saying "cannot import name 'pipeline'", while the same request
    answered in nine seconds a minute later. Nothing is wrong with the install,
    so retry until the import has finished, and only then believe the error.
    """
    deadline = time.time() + wait_seconds
    while True:
        try:
            from transformers import pipeline
            return pipeline
        except ImportError:
            if time.time() >= deadline:
                raise
            time.sleep(0.25)


class Lyricist:
    """Loads the model once and keeps it resident for later requests."""

    def __init__(self, model_id=None, device=None):
        self.model_id = model_id
        self.device = device
        self._lock = threading.Lock()
        self._pipeline = None

    def _build(self):
        import torch
        pipeline = _text_pipeline()

        if self.device is None:
            self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        dtype = torch.float16 if self.device == 'cuda' else torch.float32
        self._pipeline = pipeline(
            'text-generation',
            model=self.model_id,
            torch_dtype=dtype,
            device_map=self.device,
            model_kwargs={'low_cpu_mem_usage': True},
        )
        return self._pipeline

    @property
    def pipeline(self):
        if self._pipeline is None:
            with self._lock:
                if self._pipeline is None:
                    self._build()
        return self._pipeline

    def write_song(self, genre='electronic music', subject='', seed=0, corpus=None,
                   angle='', avoid=None):
        """Return {'sections': [{'section', 'lines'}], 'lines': [...]}."""
        generator = self.pipeline
        # The videos are context, not source material. At most a couple of words
        # are offered as a hint, and the model is free to ignore them: feeding it
        # phrase lists is what made every song the same words rearranged.
        hint_words = [str(item).strip() for item in (corpus or []) if str(item).strip()][:3]
        theme_hint = ''
        if hint_words and not subject:
            theme_hint = ' If it helps, these are near the mood: ' + ', '.join(hint_words) + '.'
        avoid = [str(line).strip() for line in (avoid or []) if str(line).strip()][-14:]
        avoid_block = ''
        if avoid:
            avoid_block = ('Do not repeat these lines or anything close to them, '
                           'and do not rhyme with them:\n' + '\n'.join(avoid) + '\n')

        prompt = SONG_PROMPT.format(
            genre=genre or 'electronic music',
            theme_hint=theme_hint[:200],
            angle=angle or 'first person, present tense',
            mood=MOODS[abs(seed) % len(MOODS)],
            avoid=avoid_block,
        )
        messages = [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': prompt},
        ]
        random.seed(seed)
        output = generator(
            messages,
            max_new_tokens=800,
            do_sample=True,
            temperature=0.92,
            top_p=0.92,
            top_k=60,
            repetition_penalty=1.12,
            no_repeat_ngram_size=3,
        )
        text = ''
        result = output[0] if output else {}
        generated = result.get('generated_text')
        if isinstance(generated, list):
            text = generated[-1].get('content', '')
        elif isinstance(generated, str):
            text = generated

        sections = parse_song(text, avoid)
        lines = [line for part in sections for line in part['lines']]
        return {'sections': sections, 'lines': lines}

    # Kept for older callers: the flat list of lines.
    def write(self, genre='electronic music', subject='', seed=0, lines=14, corpus=None,
              angle='', avoid=None):
        return self.write_song(genre, subject, seed, corpus=corpus, angle=angle,
                               avoid=avoid)['lines'][:lines]


def _section_name(raw):
    lowered = re.sub(r'\s+', ' ', raw.strip().lower())
    if 'chorus' in lowered or lowered in ('hook', 'refrain'):
        if 'pre' in lowered:
            return 'Pre-chorus'
        return 'Chorus'
    if 'bridge' in lowered:
        return 'Bridge'
    if 'intro' in lowered:
        return 'Intro'
    if 'outro' in lowered:
        return 'Outro'
    match = re.search(r'(\d+)', lowered)
    return 'Verse ' + (match.group(1) if match else '1')


def _clean_line(raw):
    line = re.sub(r'^\s*(?:\d+[.)]|[-*\u2022])\s*', '', raw).strip()
    line = line.strip('"\u2018\u2019\u201c\u201d`\' ')
    if not line or line.endswith(':'):
        return ''
    if len(line.split()) > 14:
        return ''
    if line.lower().startswith(('here are', 'sure', 'lyrics', 'note', 'title')):
        return ''
    if BANNED.search(line):
        return ''
    return line


def parse_song(text, avoid=None):
    """Turn the model's answer into sections, with one chorus repeated verbatim."""
    avoid_norm = [re.sub(r'[^a-z0-9 ]', '', str(line).lower()) for line in (avoid or [])]
    sections = []
    current = None
    for raw in str(text).splitlines():
        tag = TAG.match(raw)
        if tag:
            current = {'section': _section_name(tag.group(1)), 'lines': []}
            sections.append(current)
            continue
        line = _clean_line(raw)
        if not line:
            continue
        normal = re.sub(r'[^a-z0-9 ]', '', line.lower())
        if any(_too_similar(normal, other) for other in avoid_norm):
            continue
        if current is None:
            current = {'section': 'Verse 1', 'lines': []}
            sections.append(current)
        if current['lines'] and current['lines'][-1] == line:
            continue
        current['lines'].append(line)

    sections = [part for part in sections if part['lines']]

    # No tags in the answer: shape the lines into verses and a chorus anyway, so
    # the page still gets a song with a repeatable hook.
    if len(sections) < 2:
        pool = []
        for raw in str(text).splitlines():
            line = _clean_line(raw)
            if line and line not in pool:
                pool.append(line)
        if len(pool) < 6:
            return []
        quarter = max(2, len(pool) // 4)
        blocks = [pool[0:quarter], pool[quarter:quarter * 2],
                  pool[quarter * 2:quarter * 3]]
        return [
            {'section': 'Verse 1', 'lines': blocks[0]},
            {'section': 'Chorus', 'lines': blocks[1]},
            {'section': 'Verse 2', 'lines': blocks[2]},
            {'section': 'Chorus', 'lines': blocks[1]},
        ]

    # The chorus has to be the same words each time: take the first one and use
    # it wherever a chorus appears.
    chorus = next((part['lines'] for part in sections if part['section'] == 'Chorus'), None)
    if chorus:
        for part in sections:
            if part['section'] == 'Chorus':
                part['lines'] = list(chorus)
        if not any(part['section'] == 'Chorus' for part in sections[1:]):
            sections.insert(1, {'section': 'Chorus', 'lines': list(chorus)})
    return sections


def clean_lines(text, wanted=14, avoid=None):
    """Keep only singable lines, so a chatty answer still yields a lyric."""
    avoid = [re.sub(r'[^a-z0-9 ]', '', str(line).lower()) for line in (avoid or [])]
    lines = []
    for raw in str(text).splitlines():
        line = _clean_line(raw)
        if not line:
            continue
        normal = re.sub(r'[^a-z0-9 ]', '', line.lower())
        if any(_too_similar(normal, other) for other in avoid):
            continue
        if lines and lines[-1] == line:
            continue
        lines.append(line)
    return lines[:wanted]


def _too_similar(line, other):
    """True when two lines share most of their words."""
    words = set(line.split())
    theirs = set(other.split())
    if not words or not theirs:
        return False
    shared = len(words & theirs)
    return shared / max(len(words), len(theirs)) >= 0.75


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--genre', default='electronic music')
    parser.add_argument('--subject', default='')
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--model', default=None)
    args = parser.parse_args()

    manifest = load_manifest()
    model_id = args.model or lyrics_model_id(manifest)
    print(f'model: {model_id}', file=sys.stderr)
    lyricist = Lyricist(model_id)
    song = lyricist.write_song(args.genre, args.subject, args.seed)
    for part in song['sections']:
        print()
        print('[' + part['section'] + ']')
        for line in part['lines']:
            print(line)


if __name__ == '__main__':
    main()
