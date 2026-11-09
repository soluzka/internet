"""Show that the lyric import waits for a half-built transformers module.

The 500 on 8 Nov 2026 was `from transformers import pipeline` running while the
warm-up thread was still importing the module: present in sys.modules, no
attributes yet. This reproduces that state on purpose - the attribute appears
after a delay - and checks that _text_pipeline waits for it instead of raising.
"""

import sys
import threading
import time
import types

here = r'D:\scrape_videos\scrape_videos\scrape\scrape\my_app\scrape\song_service'

# A module that exists but has no `pipeline` yet, exactly like a half-imported one.
stub = types.ModuleType('transformers')
sys.modules['transformers'] = stub


def finish_import(delay):
    time.sleep(delay)
    def pipeline(*args, **kwargs):
        return 'pipeline reached'
    stub.pipeline = pipeline


threading.Thread(target=finish_import, args=(1.5,), daemon=True).start()

sys.path.insert(0, here)
import lyrics  # noqa: E402

started = time.time()
factory = lyrics._text_pipeline(wait_seconds=10)
waited = time.time() - started

print('returned after %.1f s' % waited)
print('factory works:', factory() == 'pipeline reached')
print('PASS' if waited >= 1.0 and factory() == 'pipeline reached' else 'FAIL')

# And a genuinely absent attribute must still fail rather than hang forever.
dead = types.ModuleType('transformers')
sys.modules['transformers'] = dead
started = time.time()
try:
    lyrics._text_pipeline(wait_seconds=1)
    print('FAIL: a missing pipeline was accepted')
except ImportError as exc:
    print('gives up after %.1f s with: %s' % (time.time() - started, exc))
