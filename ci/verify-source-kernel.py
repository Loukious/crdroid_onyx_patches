#!/usr/bin/env python3
"""Verify that the shipped Onyx images contain the current source-build outputs."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify(rom, payload):
    rom, payload = rom.resolve(), payload.resolve()
    source = rom / 'kernel/platform/kernel-6.18'
    product = rom / 'out/target/product/onyx'
    output = product / 'obj/KERNEL_OBJ'
    host = rom / 'out/host/linux-x86/bin'
    receipt = json.loads((output / 'onyx-source-build.json').read_text())
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != receipt['source']['revision']:
        raise ValueError('Packaged kernel was built from a different synced revision')
    for name, expected in receipt['sha256'].items():
        if Path(name).name != name or sha(output / name) != expected:
            raise ValueError('Source-build output changed: ' + name)
    for name, key in [('common-source-hashes.json', 'common_manifest'),
                      ('module-source-hashes.json', 'module_manifest')]:
        if sha(source / 'port' / name) != receipt['source'][key]:
            raise ValueError('Source manifest changed after build: ' + name)

    manifest = json.loads((payload / 'payload-manifest.json').read_text())
    images = {part: payload / ('payload_' + part + '.img') for part in
              ['boot', 'vendor_boot', 'vendor_dlkm', 'system_dlkm', 'dtbo', 'recovery']}
    for part, path in images.items():
        if sha(path) != manifest[part]['sha256']:
            raise ValueError('Reconstructed OTA image differs from its payload hash: ' + part)

    sys.path.insert(0, str(source / 'port'))
    spec = importlib.util.spec_from_file_location('onyx_cpio', source / 'port/recovery/generate.py')
    cpio = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cpio)

    def run(*args):
        return subprocess.check_output([str(a) for a in args])

    def check_modules(part, modules, layout=None):
        expected = {name: receipt['sha256'][name] for name in
                    (output / ((layout or part) + '.modules')).read_text().splitlines()}
        if modules != expected:
            missing = sorted(set(expected) - set(modules))
            extra = sorted(set(modules) - set(expected))
            changed = sorted(n for n in set(modules) & set(expected) if modules[n] != expected[n])
            raise ValueError(f'{part}: module mismatch missing={missing} extra={extra} changed={changed}')
        print(f'{part}: {len(modules)} packed modules match the source-build receipt')

    with tempfile.TemporaryDirectory(prefix='onyx-shipped-', dir=payload) as temp:
        work = Path(temp)
        run(host / 'unpack_bootimg', '--boot_img', images['boot'], '--out', work / 'boot')
        if sha(work / 'boot/kernel') != receipt['sha256']['Image']:
            raise ValueError('Shipped boot kernel differs from compiled GKI')
        run(host / 'unpack_bootimg', '--boot_img', images['vendor_boot'], '--out', work / 'vendor_boot')
        if sha(work / 'vendor_boot/dtb') != receipt['sha256']['dtb.img']:
            raise ValueError('Shipped DTB differs from the kernel recipe')
        dtbo = (output / 'dtbo.img').read_bytes()
        with images['dtbo'].open('rb') as stream:
            if stream.read(len(dtbo)) != dtbo:
                raise ValueError('Shipped DTBO differs from the kernel recipe')
        modules = {}
        for ramdisk in sorted((work / 'vendor_boot').glob('vendor_ramdisk*')):
            if not ramdisk.is_file():
                continue
            data = ramdisk.read_bytes()
            if not data.startswith(b'07070'):
                data = run(host / 'lz4', '-dc', ramdisk)
            for name, (_, contents, _) in cpio.cpio_entries(data).items():
                if name.endswith('.ko'):
                    short = Path(name).name
                    if short in modules:
                        raise ValueError('Duplicate vendor ramdisk module: ' + short)
                    modules[short] = hashlib.sha256(contents).hexdigest()
        check_modules('vendor_ramdisk', modules)
        run(host / 'unpack_bootimg', '--boot_img', images['recovery'], '--out', work / 'recovery')
        recovery_kernel = work / 'recovery/kernel'
        if recovery_kernel.is_file() and recovery_kernel.stat().st_size:
            if sha(recovery_kernel) != receipt['sha256']['Image']:
                raise ValueError('Shipped recovery embeds a different kernel')
        ramdisk = work / 'recovery/ramdisk'
        data = ramdisk.read_bytes()
        if not data.startswith(b'07070'):
            data = run(host / 'lz4', '-dc', ramdisk)
        recovery_modules = {}
        for name, (_, contents, _) in cpio.cpio_entries(data).items():
            if name.endswith('.ko'):
                short = Path(name).name
                if short in recovery_modules:
                    raise ValueError('Duplicate recovery module: ' + short)
                recovery_modules[short] = hashlib.sha256(contents).hexdigest()
        check_modules('recovery', recovery_modules, 'vendor_ramdisk')
        for part in ['vendor_dlkm', 'system_dlkm']:
            tree = work / part
            run(host / 'fsck.erofs', '--extract=' + str(tree), '--no-preserve-owner', images[part])
            modules = {}
            for module in tree.rglob('*.ko'):
                if module.is_symlink() or module.name in modules:
                    raise ValueError('Duplicate or linked ' + part + ' module: ' + str(module))
                modules[module.name] = sha(module)
            check_modules(part, modules)
    print('Verified OTA kernel, device trees and every module against source ' + revision)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rom', type=Path)
    parser.add_argument('payload', type=Path, help='Output directory from verify-payload.py')
    args = parser.parse_args()
    verify(args.rom, args.payload)
