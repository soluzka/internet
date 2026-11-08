"""Install the song models declared in models.json.

    song_service\\.venv\\Scripts\\python install.py            # packages + weights
    song_service\\.venv\\Scripts\\python install.py --packages   # packages only
    song_service\\.venv\\Scripts\\python install.py --weights    # weights only

Packages go through pip, so a version bump is a manifest edit rather than a
manual clone. Weights are fetched by repo id into the path the manifest names.
"""

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MANIFEST = os.path.join(HERE, 'models.json')


def load_manifest():
    with open(MANIFEST, encoding='utf-8') as handle:
        return json.load(handle)


def run(command):
    print('+', ' '.join(command))
    result = subprocess.run(command)
    if result.returncode != 0:
        raise SystemExit(f'failed: {" ".join(command)}')


def install_entries(entries, label):
    if not entries:
        return
    print(f'\n== {label} ==')
    for entry in entries:
        # A plain string is a normal PyPI/git install. An object carries its own
        # index, which is how the CUDA build of torch is selected instead of
        # silently getting the CPU one, and how pinned versions survive a mirror
        # that would otherwise hand back something newer.
        if isinstance(entry, str):
            run([sys.executable, '-m', 'pip', 'install', entry])
            continue
        command = [sys.executable, '-m', 'pip', 'install']
        if entry.get('index'):
            command += ['--index-url', entry['index']]
        command += entry.get('extra') or []
        command.append(entry['spec'])
        run(command)


def install_packages(manifest):
    cuda = manifest.get('cuda') or {}
    if cuda:
        print('CUDA:', cuda.get('runtime', 'unknown'))
        print('  wheel index:', cuda.get('index', 'default'))
        print('  driver minimum:', cuda.get('driver_min', 'unknown'))
        print(' ', cuda.get('note', ''))

    # One list for the whole service, plus any per-model extra.
    install_entries(manifest.get('packages'), 'service packages')
    for model in manifest['models']:
        install_entries(model.get('packages'), f'packages for {model["name"]}')


def check(manifest):
    """Report what is installed and what is missing, without changing anything."""
    import importlib.util

    print('== packages ==')
    imports = manifest.get('imports') or {}
    missing = []
    for label, module in imports.items():
        found = importlib.util.find_spec(module) is not None
        print(f'  {"ok " if found else "MISSING "} {label}  ({module})')
        if not found:
            missing.append(module)

    print('\n== weights ==')
    for model in manifest['models']:
        target = os.path.normpath(os.path.join(ROOT, model['target']))
        expected = float(model.get('size_gb') or 0)
        complete, actual_gb = weights_complete(target, expected)
        state = 'ok ' if complete else ('MISSING ' if actual_gb == 0 else 'PARTIAL ')
        print(f'  {state} {model["name"]}  {actual_gb:.1f} / {expected:.1f} GB  {target}')
        if not complete:
            missing.append(f'{model["name"]} ({actual_gb:.1f}/{expected:.1f} GB)')

    print('\n== versions ==')
    for label in ('torch', 'transformers', 'huggingface_hub'):
        module_name = imports.get(label)
        if not module_name:
            continue
        try:
            module = __import__(module_name)
            print(f'  {label} {getattr(module, "__version__", "unknown")}')
        except Exception as exc:  # noqa: BLE001 - a broken import is the point
            print(f'  {label} cannot import: {exc}')

    if missing:
        print('\nMissing:', ', '.join(missing))
        print('Run: install.py')
        return 1
    print('\nEverything the service needs is installed.')
    return 0


def folder_gb(target):
    total = 0
    if not os.path.isdir(target):
        return 0.0
    for root, _dirs, files in os.walk(target):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total / (1024 ** 3)


def weights_complete(target, expected_gb):
    """A partial download is not an install, so size decides, not existence."""
    actual = folder_gb(target)
    if expected_gb <= 0:
        return actual > 0, actual
    return actual >= expected_gb * 0.9, actual


def enable_parallel_transfer():
    """Use hf_transfer's chunked parallel download; it is several times faster.

    The variable must be set before huggingface_hub is imported, which is why
    this runs first and the import happens after it.
    """
    try:
        import hf_transfer  # noqa: F401
    except ImportError:
        run([sys.executable, '-m', 'pip', 'install', '--index-url',
             'https://pypi.org/simple', 'hf_transfer'])
    os.environ['HF_HUB_ENABLE_HF_TRANSFER'] = '1'
    return True


def download_weights(manifest):
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        run([sys.executable, '-m', 'pip', 'install', 'huggingface_hub'])
        from huggingface_hub import snapshot_download

    # Parallel chunks by default: the serial path measured 1.8 MB/s here, which
    # turns a 10 GB install into an hour and a half.
    if enable_parallel_transfer():
        print('parallel transfer: on (hf_transfer, 8 concurrent files)')

    for model in manifest['models']:
        repo = model.get('repo')
        if not repo:
            continue
        target = os.path.normpath(os.path.join(ROOT, model['target']))
        expected = float(model.get('size_gb') or 0)
        complete, actual = weights_complete(target, expected)
        if complete:
            print(f'\n== weights for {model["name"]}: already in {target} ({actual:.1f} GB) ==')
            continue
        os.makedirs(target, exist_ok=True)
        print(f'\n== weights for {model["name"]}: {repo} -> {target}')
        print(f'   {actual:.1f} of ~{expected:.1f} GB present, resuming ==')
        snapshot_download(repo_id=repo, local_dir=target, max_workers=8)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packages', action='store_true', help='install packages only')
    parser.add_argument('--weights', action='store_true', help='download weights only')
    parser.add_argument('--check', action='store_true', help='report what is installed, change nothing')
    args = parser.parse_args()

    manifest = load_manifest()
    if args.check:
        raise SystemExit(check(manifest))
    both = not args.packages and not args.weights
    if both or args.packages:
        install_packages(manifest)
    if both or args.weights:
        download_weights(manifest)
    print('\nDone. Check the GPU with:')
    print(f'  {sys.executable} -c "import torch; print(torch.__version__, torch.cuda.is_available())"')
    print('Then start the service with: python song_service\\app.py')


if __name__ == '__main__':
    main()
