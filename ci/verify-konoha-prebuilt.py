#!/usr/bin/env python3
"""Verify the complete repo-sync prebuilt inventory before configuring a ROM."""
import hashlib
import json
from pathlib import Path
import re
import sys

root=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parent
expected={}
for line in (root/'SHA256SUMS').read_text().splitlines():
    m=re.fullmatch(r'([0-9a-f]{64})  (.+)',line)
    if not m:raise ValueError('Invalid checksum line')
    name=Path(m[2])
    if name.is_absolute() or '..' in name.parts or str(name)!=m[2] or m[2] in expected:
        raise ValueError('Unsafe or duplicated prebuilt path')
    expected[m[2]]=m[1]
actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and '.git' not in p.relative_to(root).parts}
if actual!=set(expected)|{'SHA256SUMS'}:raise ValueError('Prebuilt inventory differs')
for name,wanted in expected.items():
    path=root/name
    if path.is_symlink():raise ValueError('Unexpected symlink')
    with path.open('rb') as f:got=hashlib.file_digest(f,'sha256').hexdigest()
    if got!=wanted:raise ValueError('Prebuilt hash mismatch: '+name)
meta=json.loads((root/'prebuilt.json').read_text())
if meta['device']!='onyx' or not meta['kernel_release'].startswith('6.18.'):
    raise ValueError('Unexpected prebuilt target')
print(f'Konoha prebuilts verified: {meta["kernel_release"]}, {meta["modules"]} modules')
