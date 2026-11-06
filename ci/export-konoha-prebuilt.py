#!/usr/bin/env python3
"""Copy an already verified Onyx 6.18 artifact and partitioned module bundle into a repo-sync tree. Never builds images or code."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess


def digest(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def export(artifact, bundle, output, revision, source_root, baseline_root):
    if not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError('Exact source commit required')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Export requires an empty output directory')
    report = json.loads((artifact / 'report.json').read_text())
    layout = json.loads((bundle / 'report.json').read_text())
    release = (artifact / 'gki/kernel.release').read_text().strip()
    if not release.startswith('6.18.') or layout['release'] != release or layout['status'] != 'PASS':
        raise ValueError('Mismatched or unverified 6.18 inputs')
    if report['kernel_release'] != release or report.get('qdss_diagnostic') is not False:
        raise ValueError('Expected verified ordinary 6.18 kernel')
    spec = importlib.util.spec_from_file_location('verify_konoha', Path(__file__).with_name('verify-konoha-modules.py'))
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    output.mkdir(parents=True, exist_ok=True)
    def copy(src, target, hashes, name):
        if digest(src) != hashes.get(name):
            raise ValueError('Input hash mismatch: ' + name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
    for src, dest in [('gki/Image','Image'), ('gki/kernel_aarch64_dot_config','kernel.config'),
                      ('gki/kernel.release','kernel.release'), ('gki/modules.builtin','modules.builtin'),
                      ('gki/modules.builtin.modinfo','modules.builtin.modinfo'),
                      ('devicetrees/dtb.img','dtb/onyx.dtb'), ('devicetrees/dtbo.img','dtbo.img')]:
        copy(artifact/src, output/dest, report['sha256'], src)
    if (output/'Image').read_bytes()[56:60] != b'ARM\x64':
        raise ValueError('Invalid ARM64 Image header')
    for name in ['common-source-hashes.json','module-source-hashes.json']:
        committed = json.loads(subprocess.check_output(['git','show',revision+':port/'+name],cwd=source_root))
        if committed != json.loads((artifact/'inputs'/name).read_text()):
            raise ValueError('Artifact source snapshot differs from selected source commit: '+name)
    shutil.copyfile(source_root/'COPYING',output/'COPYING')
    module_files=[]
    for partition in ['system_dlkm','vendor_dlkm','vendor_ramdisk']:
        directory = bundle/partition/'lib/modules'
        for path in sorted(directory.iterdir()):
            # Android regenerates dependency/alias metadata for its actual mount paths.
            if path.suffix == '.ko' or path.name in ['modules.load','modules.load.recovery','modules.blocklist','modules.options']:
                name=path.relative_to(bundle).as_posix()
                copy(path, output/name, layout['sha256'], name)
                if path.suffix == '.ko': module_files.append(output/name)
        for filename in ['modules.load','modules.load.recovery']:
            if not (directory/filename).exists(): continue
            entries=(directory/filename).read_text().splitlines()
            if len(entries)!=len(set(entries)) or any(not (directory/e).is_file() or Path(e).name!=e for e in entries):
                raise ValueError('Invalid load list: '+partition+'/'+filename)
    unique={}
    for path in module_files:
        if path.name in unique and digest(unique[path.name])!=digest(path):
            raise ValueError('Different binaries with same module name: '+path.name)
        unique[path.name]=path
    if len(unique)!=layout['modules']:
        raise ValueError('Incomplete module bundle')
    for entry in report['module_verification']:
        if entry['module'] not in unique or digest(unique[entry['module']])!=entry['sha256']:
            raise ValueError('Platform module differs from kernel artifact: '+entry['module'])
    symvers=[artifact/'gki/kernel_aarch64_Module.symvers',*sorted((artifact/'platform').glob('*_Module.symvers'))]
    for path in symvers:
        copy(path, output/'abi'/path.name, report['sha256'], path.relative_to(artifact).as_posix())
    verified=verifier.verify(list(unique.values()),symvers,release)
    (output/'module-verification.json').write_text(json.dumps(verified,indent=2)+'\n')
    # Record the unchanged upstream build and packaging evidence without local machine paths.
    (output/'prebuilt.json').write_text(json.dumps({
        'format':1,'device':'onyx','kernel_release':release,'source_repository':'Loukious/onyx-android17-6.18',
        'source_revision':revision,'platform_modules':len(report['module_verification']),'modules':len(unique),
        'source_snapshot_verified':True,'artifact_report_sha256':digest(artifact/'report.json'),'bundle_report_sha256':digest(bundle/'report.json'),
        'kernel_sha256':digest(output/'Image'),'kernelsu_next':report.get('kernelsu_next'),
        'partition_counts':{p:len(list((output/p/'lib/modules').glob('*.ko'))) for p in ['system_dlkm','vendor_dlkm','vendor_ramdisk']},
        'limits':'Existing binaries only. ROM integration statically checked; a new ROM build and hardware validation remain required.'
    },indent=2)+'\n')
    # Include syscall headers from the same GKI/module snapshot before hashing.
    spec = importlib.util.spec_from_file_location('export_konoha_headers', Path(__file__).with_name('export-konoha-headers.py'))
    headers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(headers)
    archive = output/'kernel-uapi-headers.tar.gz'
    headers.export(artifact, source_root, revision, baseline_root, archive)
    receipt = json.loads(archive.with_suffix(archive.suffix+'.json').read_text())
    meta_path = output/'prebuilt.json'
    meta = json.loads(meta_path.read_text())
    meta['uapi_headers'] = {'archive':archive.name, 'receipt':archive.name+'.json',
                            'sha256':receipt['archive_sha256'], 'headers':receipt['headers'],
                            'source_revision':receipt['source_revision']}
    meta_path.write_text(json.dumps(meta, indent=2)+'\n')
    template=Path(__file__).with_name('konoha-prebuilt-BoardConfig.mk')
    shutil.copyfile(template,output/'BoardConfig.mk')
    shutil.copyfile(Path(__file__).with_name('verify-konoha-prebuilt.py'),output/'verify.py')
    (output/'README.md').write_text('# Onyx matched Linux 6.18 prebuilts\n\n'
        'Consumed at `device/xiaomi/onyx-kernel` by the Konoha local manifest.\n'
        'Image, corrected device trees and all modules come from the same accepted artifact set.\n'
        'See prebuilt.json for exact source and input identities; `python3 verify.py` checks file hashes.\n'
        'Source: https://github.com/Loukious/onyx-android17-6.18/tree/'+revision+'\n\n'
        'Normal Android packaging generates boot/vendor_boot/recovery/DLKM and AVB/OTA metadata.\n'
        'No prebuilt ROM partition images or device-specific diagnostic metadata mounts are shipped.\n'
        'Kernel and module sources retain their upstream licenses; consult the source branch.\n')
    hashes={p.relative_to(output).as_posix():digest(p) for p in sorted(output.rglob('*')) if p.is_file()}
    (output/'SHA256SUMS').write_text(''.join(f'{v}  {k}\n' for k,v in hashes.items()))
    print(f'Exported {release}: {len(unique)} modules; no compilation or image build performed.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--artifact',required=True,type=Path);p.add_argument('--bundle',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path);p.add_argument('--source-revision',required=True);p.add_argument('--source-root',required=True,type=Path)
    p.add_argument('--baseline-root',required=True,type=Path,help='Pinned kernel/xiaomi/sm8735 ABI baseline, for legacy ION UAPI only')
    a=p.parse_args();export(a.artifact.resolve(),a.bundle.resolve(),a.output.resolve(),a.source_revision,a.source_root.resolve(),a.baseline_root.resolve())
