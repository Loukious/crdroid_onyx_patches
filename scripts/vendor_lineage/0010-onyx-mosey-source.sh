#!/usr/bin/env bash
# Reproduce the native Onyx Wonder/Mosey ROM integration after a clean sync.
set -euo pipefail
[ "${KONOHA_SOURCE_BUILD:-1}" = 1 ] || exit 0
[ "${DEVICE:-onyx}" = onyx ] || exit 0
MOSEY_ASSETS="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../assets/onyx-mosey-source" && pwd)"
python3 - "$1" "$MOSEY_ASSETS" <<'PY'
import hashlib
import json
from pathlib import Path
import shutil
import sys

lineage = Path(sys.argv[1]).resolve()
rom = lineage.parent.parent
assets = Path(sys.argv[2])
extra = rom / 'vendor/extra'
if not (extra / 'product.mk').is_file() or not (extra / 'BoardConfigExtra.mk').is_file():
    raise SystemExit('vendor/extra is missing; native Mosey cannot be integrated')
if not (rom / 'vendor/gms-mosey/mosey/mosey-vendor.mk').is_file():
    raise SystemExit('vendor/gms-mosey must be synced before native Mosey integration')
files = json.loads((assets / 'manifest.json').read_text())['files']
# Validate every asset before modifying the source tree.
for relative, digest in files.items():
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:
        raise SystemExit('Invalid native Mosey source path')
    source = assets / 'files' / path
    if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
        raise SystemExit('Native Mosey source digest mismatch: ' + relative)
for relative in sorted(files):
    source = assets / 'files' / relative
    target = extra / 'mosey' / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file() or target.read_bytes() != source.read_bytes():
        shutil.copyfile(source, target)
for filename, marker, block in [
    ('product.mk', '$(call inherit-product, vendor/extra/mosey/product.mk)',
     '# Native Mosey uses the source-built Onyx Wonder WLAN provider.\n'
     '$(call inherit-product, vendor/extra/mosey/product.mk)\n'),
    ('BoardConfigExtra.mk', 'SYSTEM_EXT_PRIVATE_SEPOLICY_DIRS += vendor/extra/mosey/sepolicy',
     '# Focused native Mosey network and launcher policy.\n'
     'SYSTEM_EXT_PRIVATE_SEPOLICY_DIRS += vendor/extra/mosey/sepolicy\n'),
]:
    path = extra / filename
    data = path.read_text()
    if marker not in data.splitlines():
        path.write_text(data.rstrip() + '\n\n' + block)
print('   ++ Native Mosey/Wonder source and exact RTM_SETLINK policy installed')
PY
