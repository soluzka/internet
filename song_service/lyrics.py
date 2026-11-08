"""Write song lyrics with a small language model, on this machine.

The page asks for lyrics before it asks for music, so this runs on the GPU (or
CPU if CUDA is unavailable) and returns plain lines.

    song_service\\.venv\\Scripts\\python lyrics.py --genre techno --subject "bass, night, city"

The model is chosen in models.json under "lyrics". Nothing here is templated:
the lines are generated, and the seed changes them.
"""

import argparse
import json
import os
import random
import re
import sys
import threading

ROOT = os.path.dirname(os.path.abspath(__file__))

SYSTEM_PROMPT = (
    'You are a songwriter. You write lyrics that could be sung over the music '
    'you are told about. You answer with lines of lyrics only, never with prose, '
    'headings or explanations.'
)

USER_PROMPT = (
    'Write 14 lines of lyrics for a {genre} song.\n'
    'Here are phrases taken from song titles and descriptions. Use them as raw '
    'material: pick the images and sounds that feel like weather, places, people, '
    'machines, or feelings, and write your own lines around them. Mix them up, '
    'change the wording, invent what is missing.\n'
    'Phrases: {subject}.\n'
    'Rules:\n'
    '- Never mention a library, a database, a collection, a playlist, a search, '
    'the internet, videos, tracks, an index or a count of anything. If you are '
    'tempted to describe where the words came from, write about the night instead.\n'
    '- Everyday concrete images, not metaphors about music or technology.\n'
    '- One short repeated line that could work as the hook.\n'
    '- Present tense, first or second person.\n'
    '- Under twelve words per line, no rhyme forced into place.\n'
    '- No headings, no numbering, no quotes, no explanation.\n'
    'Return only the lines, one per line.'
)

# Lines that describe the collection instead of a life are thrown away rather
# than shown as lyrics.
BANNED = re.compile(
    r'\b(libraries|library|database|databases|collection|playlist|playlists|'
    r'search\w*|index|indexed|algorithm|metadata|catalog\w*|archiv\w+|'
    r'tracks?|videos?|clips?|uploads?|channels?|subscri\w+|results?)\b',
    re.I,
)


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


class Lyricist:
    """Loads the model once and keeps it resident for later requests."""

    def __init__(self, model_id=None, device=None):
        self.model_id = model_id
        self.device = device
        self._lock = threading.Lock()
        self._pipeline = None

    def _build(self):
        import torch
        from transformers import pipeline

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

    def write(self, genre='electronic music', subject='', seed=0, lines=14, corpus=None):
        generator = self.pipeline
        material = ', '.join(corpus) if corpus else (subject or 'night, movement, weather')
        prompt = USER_PROMPT.format(
            genre=genre or 'electronic music',
            subject=material[:1200],
        )
        messages = [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': prompt},
        ]
        random.seed(seed)
        output = generator(
            messages,
            max_new_tokens=420,
            do_sample=True,
            temperature=0.95,
            top_p=0.92,
            repetition_penalty=1.08,
        )
        text = ''
        result = output[0] if output else {}
        generated = result.get('generated_text')
        if isinstance(generated, list):
            text = generated[-1].get('content', '')
        elif isinstance(generated, str):
            text = generated
        return clean_lines(text, lines)


def clean_lines(text, wanted=14):
    """Keep only singable lines, so a chatty answer still yields a lyric."""
    lines = []
    for raw in str(text).splitlines():
        line = re.sub(r'^\s*(?:\d+[.)]|[-*\u2022])\s*', '', raw).strip()
        line = line.strip('"\'` ')
        if not line or line.endswith(':'):
            continue
        if len(line.split()) > 14:
            continue
        if line.lower().startswith(('here are', 'sure', 'lyrics', 'note')):
            continue
        if BANNED.search(line):
            continue
        lines.append(line)
    # Drop an echoed prompt or a repeated line run.
    unique = []
    for line in lines:
        if unique and unique[-1] == line:
            continue
        unique.append(line)
    return unique[:wanted]


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
    lines = lyricist.write(args.genre, args.subject, args.seed)
    for line in lines:
        print(line)


if __name__ == '__main__':
    main()
