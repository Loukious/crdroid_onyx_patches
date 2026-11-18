#!/usr/bin/env python3
"""Test and reproducibly build the scoped Android ARM64 shared-cache helper."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
SOURCES = (HERE / 'cache-overlay.cpp', HERE / 'snapshot-contract.h')
TEST_SOURCE = HERE.parent / 'test_cache_overlay.py'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes():
    return {path.name: sha(path) for path in SOURCES}


def stable(expected, test_digest):
    if source_hashes() != expected or sha(TEST_SOURCE) != test_digest:
        raise RuntimeError('Cache helper sources or tests changed during validation/build')


def captured(argv, cwd):
    return subprocess.run([str(x) for x in argv], cwd=cwd,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def checked(argv, cwd):
    result = captured(argv, cwd)
    if result.returncode:
        raise RuntimeError('Command failed: ' + ' '.join(str(x) for x in argv) + '\n' +
                           result.stderr.decode('utf-8', errors='replace'))
    return result


def verify_elf(data):
    if len(data) < 64 or data[:6] != b'\x7fELF\x02\x01':
        raise ValueError('Output must be a little-endian ELF64')
    if struct.unpack_from('<HH', data, 16) != (3, 183):
        raise ValueError('Output must be an ARM64 ET_DYN executable')
    phoff = struct.unpack_from('<Q', data, 32)[0]
    phsize, phcount = struct.unpack_from('<HH', data, 54)
    if phsize != 56 or not phcount or phoff + phsize * phcount > len(data):
        raise ValueError('Invalid ELF program headers')
    loads, dynamic, interp = [], None, None
    for index in range(phcount):
        kind, flags, offset, virtual, _, filesz, memsz, alignment = struct.unpack_from(
            '<IIQQQQQQ', data, phoff + index * phsize)
        if offset + filesz > len(data) or filesz > memsz:
            raise ValueError('Invalid ELF segment bounds')
        if kind == 1:
            if (alignment < 16384 or alignment & (alignment - 1) or
                    (offset - virtual) % alignment):
                raise ValueError('Every LOAD segment must have at least 16 KiB alignment')
            loads.append({'offset': offset, 'virtual_address': virtual,
                          'file_size': filesz, 'alignment': alignment, 'flags': flags})
        elif kind == 2:
            if dynamic is not None or filesz % 16:
                raise ValueError('Invalid ELF dynamic segment')
            dynamic = (offset, filesz)
        elif kind == 3:
            interp = data[offset:offset + filesz].rstrip(b'\0')
    if not loads or dynamic is None or interp != b'/system/bin/linker64':
        raise ValueError('Output must use the Android ARM64 PIE linker')
    tags, needed = {}, []
    terminated = False
    for pos in range(dynamic[0], dynamic[0] + dynamic[1], 16):
        tag, value = struct.unpack_from('<qQ', data, pos)
        if tag == 0:
            terminated = True
            break
        if tag == 1:
            needed.append(value)
        elif tag in (5, 10, 0x6ffffffb):
            if tag in tags:
                raise ValueError('Duplicate ELF dynamic field')
            tags[tag] = value
    if not terminated or not tags.get(0x6ffffffb, 0) & 0x08000000:
        raise ValueError('ELF does not declare DF_1_PIE')
    if 5 not in tags or 10 not in tags:
        raise ValueError('ELF string table is missing')
    string_offset = None
    for load in loads:
        delta = tags[5] - load['virtual_address']
        if 0 <= delta and delta + tags[10] <= load['file_size']:
            string_offset = load['offset'] + delta
            break
    if string_offset is None:
        raise ValueError('ELF string table is outside a LOAD segment')
    strings = data[string_offset:string_offset + tags[10]]
    dependencies = []
    for offset in needed:
        end = strings.find(b'\0', offset)
        if offset >= len(strings) or end < 0:
            raise ValueError('Invalid DT_NEEDED name')
        dependencies.append(strings[offset:end].decode('ascii'))
    if 'libc++_shared.so' in dependencies:
        raise ValueError('Helper must statically link the C++ runtime')
    return {'passed': True, 'pie': True, 'load_segments': loads,
            'dt_needed': dependencies, 'cxx_shared_dependency': False}


def build(args):
    ndk = args.ndk.resolve()
    compiler = ndk / 'toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android35-clang++'
    properties = ndk / 'source.properties'
    for path in (*SOURCES, TEST_SOURCE, compiler, properties):
        if not path.is_file():
            raise RuntimeError(f'Required build input is missing: {path}')
    host_name = os.environ.get('CXX', 'c++')
    host_compiler = shutil.which(host_name)
    if host_compiler is None:
        raise RuntimeError(f'Host C++ compiler is unavailable: {host_name}')
    output, receipt_path = args.output.resolve(), args.receipt.resolve()
    if output in SOURCES or output == TEST_SOURCE or output == Path(__file__).resolve():
        raise RuntimeError('Output must not overwrite a source file')
    if receipt_path == output or receipt_path in SOURCES or receipt_path == TEST_SOURCE:
        raise RuntimeError('Receipt path conflicts with a source or output')
    output.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    before, test_digest = source_hashes(), sha(TEST_SOURCE)
    stdout_log = receipt_path.with_suffix('.tests.stdout.log')
    stderr_log = receipt_path.with_suffix('.tests.stderr.log')
    with tempfile.TemporaryDirectory(prefix='onyx-mosey-cache-build-') as work:
        work = Path(work)
        host = work / 'onyx-mosey-cache-host'
        host_command = [host_compiler, '-std=c++17', '-O2', '-Wall', '-Wextra',
                        '-DMOSEY_CACHE_HOST_TEST', 'cache-overlay.cpp', '-o', host]
        checked(host_command, HERE)
        stable(before, test_digest)
        test_command = [sys.executable, TEST_SOURCE, '--helper', host]
        result = captured(test_command, HERE.parent)
        stdout_log.write_bytes(result.stdout)
        stderr_log.write_bytes(result.stderr)
        if result.returncode:
            raise RuntimeError(f'Cache overlay tests failed ({result.returncode}); see {stderr_log}')
        stable(before, test_digest)
        tests = {'test_cache_overlay': {'passed': True, 'exit_code': 0}}
        summary = (result.stdout + result.stderr).decode('utf-8', errors='replace')
        match = re.search(r'Ran (\d+) tests? in ', summary)
        if not match or int(match.group(1)) == 0 or not re.search(r'^OK\s*$', summary, re.MULTILINE):
            raise RuntimeError('Successful unittest summary with at least one test is required')
        tests['test_cache_overlay']['test_count'] = int(match.group(1))
        fd, temporary_name = tempfile.mkstemp(prefix='.onyx-mosey-cache-build-', dir=output.parent)
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            arm_command = [compiler, '-std=c++17', '-O2', '-Wall', '-Wextra',
                           '-static-libstdc++', '-fPIE', '-pie',
                           '-Wl,-z,max-page-size=16384', '-Wl,-z,common-page-size=16384',
                           '-Wl,--build-id=sha1', 'cache-overlay.cpp', '-o', temporary]
            checked(arm_command, HERE)
            stable(before, test_digest)
            elf = verify_elf(temporary.read_bytes())
            tests['arm64_pie_and_static_cxx'] = {'passed': True}
            compiler_version = checked([compiler, '--version'], HERE).stdout.decode().strip()
            stable(before, test_digest)
            temporary.chmod(0o755)
            os.replace(temporary, output)
            receipt = {'passed': True, 'helper_sha256': sha(output),
                       'helper_size': output.stat().st_size, 'architecture': 'aarch64',
                       'android_api': 35, 'source_sha256': before, 'tests': tests,
                       'test_source_sha256': test_digest,
                       'test_command': [str(x) for x in test_command],
                       'test_logs': {'stdout': str(stdout_log), 'stderr': str(stderr_log),
                                     'stdout_sha256': sha(stdout_log), 'stderr_sha256': sha(stderr_log)},
                       'ndk_path': str(ndk), 'ndk_source_properties': properties.read_text(),
                       'ndk_source_properties_sha256': sha(properties),
                       'compiler_version': compiler_version, 'compiler_sha256': sha(compiler.resolve()),
                       'compile_argv': [str(x) for x in arm_command],
                       'host_compile_argv': [str(x) for x in host_command], 'elf_validation': elf}
            stable(before, test_digest)
            receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
            print(json.dumps({'passed': True, 'helper_sha256': receipt['helper_sha256'],
                              'test_count': tests['test_cache_overlay']['test_count'],
                              'receipt': str(receipt_path)}, indent=2))
        finally:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ndk', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=HERE / 'onyx-mosey-cache-arm64')
    parser.add_argument('--receipt', type=Path, default=HERE / 'build-cache-receipt.json')
    args = parser.parse_args()
    output, receipt = args.output.resolve(), args.receipt.resolve()
    products = (output, receipt, receipt.with_suffix('.tests.stdout.log'),
                receipt.with_suffix('.tests.stderr.log'))
    protected = {*SOURCES, TEST_SOURCE, Path(__file__).resolve(),
                 args.ndk.resolve() / 'source.properties',
                 args.ndk.resolve() / 'toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android35-clang++'}
    if len(set(products)) != len(products) or any(path in protected for path in products):
        parser.error('Output, receipt and test logs must be distinct and must not overwrite build inputs')
    try:
        build(args)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps({'passed': False, 'error': str(error)}, indent=2) + '\n')
        print(f'Cache helper build rejected: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
