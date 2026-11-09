"""One lock for importing transformers.

The lyric model and the music model both import transformers, and both warm-up
threads start at once. A module that is still executing in another thread is
already in sys.modules without its attributes yet, so the second import raises
instead of waiting:

    warm load failed: cannot import name 'CLIPTextModelWithProjection' from 'transformers'
    lyric model failed: cannot import name 'pipeline' from 'transformers'

Neither was a broken install. Importing transformers once, under this lock,
before either library is touched, means nobody can observe it half-built.
"""

import threading

_import_lock = threading.RLock()


def import_transformers():
    """Return a fully imported transformers, importing it if this thread is first.

    The lock is held across the import itself, so a thread that arrives while the
    module is still executing waits instead of reading an incomplete module.
    """
    with _import_lock:
        import transformers
        return transformers
