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


def install_packages(manifest):
    cuda = manifest.get('cuda') or {}
    if cuda:
        print('CUDA:', cuda.get('runtime', 'unknown'))
        print('  wheel index:', cuda.get('index', 'default'))
        print('  driver minimum:', cuda.get('driver_min', 'unknown'))
        print(' ', cuda.get('note', ''))

    for model in manifest['models']:
        packages = model.get('packages') or []
        if not packages:
            continue
        print(f'\n== packages for {model["name"]} ==')
        for entry in packages:
            # A plain string is a normal PyPI/git install. An object carries its
            # own index, which is how the CUDA build of torch is selected
            # instead of silently getting the CPU one.
            if isinstance(entry, str):
                run([sys.executable, '-m', 'pip', 'install', entry])
                continue
            command = [sys.executable, '-m', 'pip', 'install']
            if entry.get('index'):
                command += ['--index-url', entry['index']]
            command += entry.get('extra') or []
            command.append(entry['spec'])
            run(command)


def download_weights(manifest):
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        run([sys.executable, '-m', 'pip', 'install', 'huggingface_hub'])
        from huggingface_hub import snapshot_download

    for model in manifest['models']:
        repo = model.get('repo')
        if not repo:
            continue
        target = os.path.normpath(os.path.join(ROOT, model['target']))
        if os.path.isdir(target) and os.listdir(target):
            print(f'\n== weights for {model["name"]}: already in {target} ==')
            continue
        os.makedirs(target, exist_ok=True)
        print(f'\n== weights for {model["name"]}: {repo} -> {target} ==')
        snapshot_download(repo_id=repo, local_dir=target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packages', action='store_true', help='install packages only')
    parser.add_argument('--weights', action='store_true', help='download weights only')
    args = parser.parse_args()

    manifest = load_manifest()
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
