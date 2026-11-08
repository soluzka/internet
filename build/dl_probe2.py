import traceback

import yt_dlp
from yt_dlp.networking.impersonate import ImpersonateTarget

print('yt-dlp', yt_dlp.version.__version__)

with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
    try:
        targets = ydl._get_available_impersonate_targets()
        print('available targets:')
        for handler, target in targets[:12]:
            print('  ', handler, '->', target)
    except Exception:  # noqa: BLE001
        traceback.print_exc()

print('from_str chrome:', ImpersonateTarget.from_str('chrome'))
print('from_str chrome-136:', ImpersonateTarget.from_str('chrome-136'))

for label, value in (('str', 'chrome'), ('target', ImpersonateTarget('chrome'))):
    opts = {'quiet': False, 'no_warnings': False, 'impersonate': value, 'skip_download': True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info('https://www.youtube.com/watch?v=jNQXAC9IVRw', download=False)
        print(label, 'OK', info.get('title'))
    except Exception as exc:  # noqa: BLE001
        print(label, 'FAILED', type(exc).__name__, str(exc)[:200])
