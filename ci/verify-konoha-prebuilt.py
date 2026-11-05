#!/usr/bin/env python3
"""Verify the complete repo-sync prebuilt inventory before configuring a ROM."""
import hashlib
import json
from pathlib import Path
import re
import sys
import tarfile

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
if 'uapi_headers' in meta:
    headers=meta['uapi_headers']
    archive=root/headers['archive']
    receipt=json.loads((root/headers['receipt']).read_text())
    if headers['sha256']!=expected.get(headers['archive']) or receipt['archive_sha256']!=headers['sha256']:
        raise ValueError('UAPI archive provenance mismatch')
    if receipt['source_revision']!=meta['source_revision'] or headers['source_revision']!=meta['source_revision']:
        raise ValueError('UAPI source revision mismatch')
    with tarfile.open(archive) as tar:
        members=tar.getmembers()
        if any(not m.isfile() or Path(m.name).is_absolute() or '..' in Path(m.name).parts or not m.name.startswith('usr/include/') for m in members):
            raise ValueError('Unsafe UAPI archive entry')
        names={m.name for m in members}
        if len(names)!=len(members) or len(names)!=headers['headers'] or len(names)!=receipt['headers']:
            raise ValueError('UAPI header inventory mismatch')
        required={'usr/include/'+h for h in ['linux/msm_ipa.h','linux/ion.h','linux/msm_ion.h','linux/msm_ion_ids.h','asm/signal.h','asm-generic/signal.h','linux/eventpoll.h']}
        if not required<=names:
            raise ValueError('Missing required userspace headers: '+str(required-names))
print(f'Konoha prebuilts verified: {meta["kernel_release"]}, {meta["modules"]} modules')
