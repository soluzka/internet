"""Print which optional audio packages are importable in this interpreter."""

import importlib.util

for name in ('faster_whisper', 'whisper', 'yt_dlp', 'soundfile', 'numpy', 'torch'):
    print(f'{name}: {"yes" if importlib.util.find_spec(name) else "no"}')
