"""Parse-check the inline page scripts and worker.js without a browser."""
import re

import esprima

html = open('public/index.html', encoding='utf-8').read()
blocks = re.findall(r'<script(?![^>]*src=)[^>]*>(.*?)</script>', html, re.S)
bad = 0
for index, block in enumerate(blocks):
    if not block.strip():
        continue
    try:
        esprima.parseScript(block)
    except Exception as exc:  # noqa: BLE001 - report whatever the parser says
        bad += 1
        print('inline block', index, 'FAILED:', str(exc)[:200])
print('inline blocks:', len(blocks), 'failures:', bad)

source = open('worker.js', encoding='utf-8').read()
try:
    esprima.parseModule(source)
    print('worker.js parsed as module')
except Exception as exc:  # noqa: BLE001
    print('worker.js FAILED:', str(exc)[:200])
