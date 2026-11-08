"""Report whether torch sees the GPU, so setup can be checked in one command."""

import sys

try:
    import torch
except ImportError:
    print('torch: not installed')
    sys.exit(1)

print('torch:', torch.__version__)
print('cuda available:', torch.cuda.is_available())
if torch.cuda.is_available():
    print('device:', torch.cuda.get_device_name(0))
    free, total = torch.cuda.mem_get_info()
    print(f'vram: {free / 1024 ** 3:.1f} GiB free of {total / 1024 ** 3:.1f} GiB')
    print('capability:', '.'.join(str(part) for part in torch.cuda.get_device_capability(0)))
else:
    print('This is the CPU build, or the driver is not visible to torch.')
