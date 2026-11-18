#!/usr/bin/env python3
"""Build a trusted ROM AIAI prebuilt with a direct calendar correction.

Keeps Google's original signer metadata; Google did not sign the modified
contents. No Android device actions or package-verification changes are made.
"""
from __future__ import annotations
import argparse
import copy
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import zipfile

INPUT_SHA256 = '417c0a7aa18f7c54174bba33bf02fba623ead200f4a54cd0ce66c57d6c8fdc1a'
BLOCK_SHA256 = '1edd9fdff7d6ea5f9d29578770e8415fb97e540b35ab44141ad40dc026c788f6'
OLD_VERSION, NEW_VERSION = 17000140, 17000142
OLD_NAME = 'C.9.playstore.pixel11.1009419057'
NEW_NAME = OLD_NAME + '.onyx.2'
BRIDGE = 'Ldev/loukious/onyx/smartspacefix/CalendarBridge;'
OWN_PACKAGE = 'dev/loukious/onyx/smartspacefix/'
METHODS = re.compile(r'^\.method[^\n]+\n.*?^\.end method', re.M | re.S)
SIGNATURES = {
    "sam": {
        "<init>(Lyjy;Laknf;Landroid/content/Context;Lhkp;Lhkp;Lamdm;Ljava/util/concurrent/Executor;Lsan;Ltms;Lagmg;Ltbf;Lsbe;Lnas;)V": "79ab7a3478111c2a0606867e0e3a56fb303a2fe402aaf63b5f41cccbb0766322",
        "c(Ljava/lang/String;Landroid/app/smartspace/SmartspaceTargetEvent;Lalus;)Ljava/lang/Object;": "f09a25710b9ab7e7842d0d649e79ffb102e6e399741dd3b35f703d3db40655ea",
        "j(ZLalus;)Ljava/lang/Object;": "ec0ab11bfc64e91fe257644748d6479d7b0af1c8190b946c4573e6e8a1d715b4",
        "v(Lalus;)Ljava/lang/Object;": "d2d23df6bfaf736c76c8cfa3da4b7dd68649593e4e0fe6c003eadb8ea81ac533",
        "x(Ljava/util/List;)V": "d1b973942b655e4dce3ac69b2d21d26c1b61a07feb7fed5781009e54fcdd8dfc",
        "y(Ljava/util/List;)V": "6ec43089aae1f06448f61f5d951a29578387ef4fdf339bf8c4d8ab05c98b3991"
    },
    "tx": {
        "a(Ljava/lang/String;Lsp;)Lsn;": "0a1e6a8b8cbd96c7306c583ba0ceb2a1dc744031daaf5cfb69157e6d2afc3231"
    },
    "ud": {
        "a()Lagpl;": "8db7013367901858041a5ce8e91b32af1d5544f4490a237df1604ba5309c7ef7"
    }
}
CTOR_ANCHOR = '    iput-object p3, p0, Lsam;->b:Landroid/content/Context;'
CTOR_CALL = f'    invoke-static {{p0, p3}}, {BRIDGE}->initialize(Ljava/lang/Object;Landroid/content/Context;)V'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def run(argv, capture=False):
    result = subprocess.run(list(map(str, argv)), check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout or ''

def signature(method):
    return method.splitlines()[0].split()[-1]

def alias(sig):
    return 'onyx$original$' + sig

def wrapper(klass, sig):
    name = sig.split('(')[0]
    native = f'L{klass};->{alias(sig)}'
    if klass == 'sam' and name == 'v':
        lines = [f'invoke-static/range {{p0 .. p1}}, {BRIDGE}->beforeRefresh(Ljava/lang/Object;Ljava/lang/Object;)V',
                 f'invoke-virtual/range {{p0 .. p1}}, {native}', 'move-result-object v0', 'return-object v0']
    elif klass == 'sam' and name in ('x', 'y'):
        before, after = ('beforeUpsert', 'afterUpsert') if name == 'y' else ('beforeRemove', 'afterRemove')
        lines = ([f'invoke-static/range {{p0 .. p1}}, {BRIDGE}->normalizeCalendarEntries(Ljava/lang/Object;Ljava/util/List;)Ljava/util/List;',
                  'move-result-object p1'] if name == 'y' else []) + [
                 f'invoke-static/range {{p0 .. p1}}, {BRIDGE}->{before}(Ljava/lang/Object;Ljava/util/List;)V',
                 f'invoke-virtual/range {{p0 .. p1}}, {native}',
                 f'invoke-static/range {{p0 .. p0}}, {BRIDGE}->{after}(Ljava/lang/Object;)V', 'return-void']
    elif klass == 'sam' and name == 'j':
        lines = [f'invoke-static/range {{p0 .. p0}}, {BRIDGE}->beforeSelect(Ljava/lang/Object;)V',
                 f'invoke-virtual/range {{p0 .. p2}}, {native}', 'move-result-object v0',
                 f'invoke-static {{p0, p1, v0}}, {BRIDGE}->afterSelect(Ljava/lang/Object;ZLjava/lang/Object;)Ljava/lang/Object;',
                 'move-result-object v0', 'return-object v0']
    elif klass == 'sam' and name == 'c':
        lines = [f'invoke-static {{p0, p2}}, {BRIDGE}->beforeDismiss(Ljava/lang/Object;Ljava/lang/Object;)V',
                 f'invoke-virtual/range {{p0 .. p3}}, {native}', 'move-result-object v0',
                 f'invoke-static {{p0, p2}}, {BRIDGE}->afterDismiss(Ljava/lang/Object;Ljava/lang/Object;)V', 'return-object v0']
    elif klass == 'tx':
        lines = [f'invoke-virtual/range {{p0 .. p2}}, {native}', 'move-result-object v0',
                 f'invoke-static {{v0, p1}}, {BRIDGE}->markSearch(Ljava/lang/Object;Ljava/lang/String;)V', 'return-object v0']
    elif klass == 'ud':
        lines = [f'invoke-static/range {{p0 .. p0}}, {BRIDGE}->readAllPages(Ljava/lang/Object;)Ljava/lang/Object;',
                 'move-result-object v0', 'if-eqz v0, :onyx_pages_fallback', 'check-cast v0, Lagpl;', 'return-object v0',
                 ':onyx_pages_fallback', f'invoke-virtual/range {{p0 .. p0}}, {native}', 'move-result-object v0', 'return-object v0']
    else:
        raise ValueError(f'Unsupported wrapper: {klass}.{sig}')
    return f'.method public final {sig}\n    .locals 1\n\n' + '\n'.join('    ' + line for line in lines) + '\n.end method'

def patch_class(klass, source):
    found = {signature(m.group()): m.group() for m in METHODS.finditer(source)}
    replacements, additions = {}, []
    for sig, expected in SIGNATURES[klass].items():
        method = found.get(sig)
        if method is None or sha(method.encode()) != expected:
            raise ValueError(f'Unsupported exact C.9 contract: {klass}.{sig}')
        if sig.startswith('<init>'):
            if method.count(CTOR_ANCHOR) != 1:
                raise ValueError('Constructor context assignment differs')
            replacements[sig] = method.replace(CTOR_ANCHOR, CTOR_ANCHOR + '\n\n' + CTOR_CALL)
        else:
            if alias(sig) in found:
                raise ValueError('Native alias already exists')
            header, body = method.split('\n', 1)
            replacements[sig] = header.replace(sig, alias(sig)) + '\n' + body
            additions.append(wrapper(klass, sig))
    modified = METHODS.sub(lambda m: replacements.get(signature(m.group()), m.group()), source)
    return modified.rstrip() + '\n\n' + '\n\n'.join(additions) + '\n'

def xml_chunks(xml):
    if struct.unpack_from('<HHI', xml) != (3, 8, len(xml)):
        raise ValueError('Invalid binary Android XML header')
    offset, result = 8, []
    while offset < len(xml):
        typ, header, size = struct.unpack_from('<HHI', xml, offset)
        if header < 8 or size < header or offset + size > len(xml):
            raise ValueError('Invalid binary Android XML chunk')
        result.append((offset, typ, header, size))
        offset += size
    return result

def read_length(data, offset, utf8):
    if utf8:
        first = data[offset]
        return (((first & 0x7f) << 8) | data[offset + 1], offset + 2) if first & 0x80 else (first, offset + 1)
    first = struct.unpack_from('<H', data, offset)[0]
    return (((first & 0x7fff) << 16) | struct.unpack_from('<H', data, offset + 2)[0], offset + 4) if first & 0x8000 else (first, offset + 2)

def encode_length(size, utf8):
    if utf8:
        return bytes([size]) if size < 0x80 else bytes([0x80 | (size >> 8), size & 0xff])
    return struct.pack('<H', size) if size < 0x8000 else struct.pack('<HH', 0x8000 | (size >> 16), size & 0xffff)

def string_pool(pool):
    header = struct.unpack_from('<H', pool, 2)[0]
    count, _, flags, data_start = struct.unpack_from('<IIII', pool, 8)
    utf8, strings, records = bool(flags & 0x100), [], []
    for index in range(count):
        start = data_start + struct.unpack_from('<I', pool, header + 4 * index)[0]
        units, text_start = read_length(pool, start, utf8)
        if utf8:
            length, text_start = read_length(pool, text_start, True)
            end = text_start + length + 1
            strings.append(pool[text_start:text_start + length].decode('utf-8'))
        else:
            end = text_start + 2 * units + 2
            strings.append(pool[text_start:text_start + 2 * units].decode('utf-16le'))
        records.append((start, end))
    return strings, records, utf8

def manifest_attributes(xml):
    offset, _, _, size = next(chunk for chunk in xml_chunks(xml) if chunk[1] == 1)
    strings, _, _ = string_pool(xml[offset:offset + size])
    for pos, typ, header, _ in xml_chunks(xml):
        if typ != 0x102 or strings[struct.unpack_from('<I', xml, pos + header + 4)[0]] != 'manifest':
            continue
        start, attr_size, count = struct.unpack_from('<HHH', xml, pos + header + 8)
        if attr_size != 20:
            raise ValueError('Unexpected binary manifest attribute layout')
        attrs = {}
        for i in range(count):
            position = pos + header + start + i * attr_size
            _, name, raw = struct.unpack_from('<III', xml, position)
            attrs[strings[name]] = (position, raw, xml[position + 15], struct.unpack_from('<I', xml, position + 16)[0])
        return strings, attrs, (offset, size)
    raise ValueError('Manifest root missing')

def patch_manifest(xml):
    strings, attrs, (pool_offset, pool_size) = manifest_attributes(xml)
    code, name, package = attrs['versionCode'], attrs['versionName'], attrs['package']
    if code[2:] != (0x10, OLD_VERSION) or name[2] != 3 or strings[name[3]] != OLD_NAME:
        raise ValueError('Unsupported manifest version')
    if package[2] != 3 or strings[package[3]] != 'com.google.android.as' or name[1] != name[3]:
        raise ValueError('Unsupported manifest identity/encoding')
    changed = bytearray(xml)
    struct.pack_into('<I', changed, code[0] + 16, NEW_VERSION)
    pool = bytes(changed[pool_offset:pool_offset + pool_size])
    old_strings, records, utf8 = string_pool(pool)
    start, end = records[name[3]]
    encoded = encode_length(len(NEW_NAME.encode('utf-16le')) // 2, utf8)
    text = NEW_NAME.encode('utf-8' if utf8 else 'utf-16le')
    encoded += (encode_length(len(text), True) if utf8 else b'') + text + (b'\0' if utf8 else b'\0\0')
    header = struct.unpack_from('<H', pool, 2)[0]
    count = struct.unpack_from('<I', pool, 8)[0]
    strings_start, styles_start = struct.unpack_from('<II', pool, 20)
    data_end = styles_start or pool_size
    delta = len(encoded) - (end - start)
    data = pool[strings_start:start] + encoded + pool[end:data_end]
    padding = (-len(data)) % 4
    new_pool = bytearray(pool[:strings_start] + data + bytes(padding) + pool[data_end:])
    struct.pack_into('<I', new_pool, 4, len(new_pool))
    if styles_start:
        struct.pack_into('<I', new_pool, 24, styles_start + delta + padding)
    for i in range(count):
        location = header + 4 * i
        original_offset = struct.unpack_from('<I', pool, location)[0]
        if original_offset > start - strings_start:
            struct.pack_into('<I', new_pool, location, original_offset + delta)
    final = bytearray(changed[:pool_offset] + new_pool + changed[pool_offset + pool_size:])
    struct.pack_into('<I', final, 4, len(final))
    final_strings, final_attrs, _ = manifest_attributes(bytes(final))
    expected = [NEW_NAME if record[0] == start else value for value, record in zip(old_strings, records)]
    if final_strings != expected or final_attrs['versionCode'][3] != NEW_VERSION:
        raise ValueError('Binary manifest verification failed')
    return bytes(final)

def eocd_offset(data):
    offset = data.rfind(b'PK\x05\x06', max(0, len(data) - 65557))
    if offset < 0 or offset + 22 + struct.unpack_from('<H', data, offset + 20)[0] != len(data):
        raise ValueError('Unsupported ZIP end-of-central-directory')
    if struct.unpack_from('<HH', data, offset + 4) != (0, 0):
        raise ValueError('Multi-disk ZIP unsupported')
    return offset

def signing_block(data):
    directory = struct.unpack_from('<I', data, eocd_offset(data) + 16)[0]
    if data[directory - 16:directory] != b'APK Sig Block 42':
        raise ValueError('APK signing block missing')
    size = struct.unpack_from('<Q', data, directory - 24)[0]
    block = data[directory - size - 8:directory]
    if struct.unpack_from('<Q', block)[0] != size or sha(block) != BLOCK_SHA256:
        raise ValueError('Unexpected Google signing block')
    return block

def insert_block(data, block):
    eocd = eocd_offset(data)
    directory = struct.unpack_from('<I', data, eocd + 16)[0]
    tail = bytearray(data[eocd:])
    struct.pack_into('<I', tail, 16, directory + len(block))
    output = data[:directory] + block + data[directory:eocd] + tail
    if signing_block(output) != block:
        raise ValueError('Signing block retention failed')
    return output

def inventory(directory):
    return {path.relative_to(directory).as_posix(): path.read_text() for path in directory.glob('smali*/**/*.smali')}

def normal(source):
    lines = []
    for line in source.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        # DexWriter omits explicit default static values. These declarations
        # describe the same field value before and after assembly.
        line = re.sub(r'^(\.field .*\bstatic\b.*:I) = 0x0$', r'\1', line)
        line = re.sub(r'^(\.field .*\bstatic\b.*:Z) = false$', r'\1', line)
        lines.append(line)
    return '\n'.join(lines)

def normal_wrapper(source):
    labels = {}
    for label in re.findall(r':[A-Za-z_][A-Za-z_0-9]*', source):
        labels.setdefault(label, f':label_{len(labels)}')
    for label in sorted(labels, key=len, reverse=True):
        source = source.replace(label, labels[label])
    return normal(source)

def verify_code(original, final, helper):
    relocations = {f'smali_classes2/{klass}.smali': f'smali_classes6/{klass}.smali' for klass in SIGNATURES}
    expected_paths = {relocations.get(path, path) for path in original} | set(helper)
    if set(final) != expected_paths:
        raise ValueError('Unexpected class inventory')
    changed = []
    for path, source in original.items():
        result, klass = final[relocations.get(path, path)], Path(path).stem
        if klass not in SIGNATURES or Path(path).parent.name != 'smali_classes2':
            if normal(source) != normal(result):
                raise ValueError(f'Unrelated class changed: {path}')
            continue
        old = {signature(m.group()): m.group() for m in METHODS.finditer(source)}
        new = {signature(m.group()): m.group() for m in METHODS.finditer(result)}
        aliases = {alias(s) for s in SIGNATURES[klass] if not s.startswith('<init>')}
        if set(new) != set(old) | aliases or normal(METHODS.sub('', source)) != normal(METHODS.sub('', result)):
            raise ValueError(f'Unexpected method inventory or class metadata: {klass}')
        for sig, method in old.items():
            if sig not in SIGNATURES[klass]:
                if normal(method) != normal(new[sig]):
                    raise ValueError(f'Unrelated method changed: {klass}.{sig}')
            elif sig.startswith('<init>'):
                expected = method.replace(CTOR_ANCHOR, CTOR_ANCHOR + '\n\n' + CTOR_CALL)
                if normal(expected) != normal(new[sig]):
                    raise ValueError('Unexpected constructor instrumentation')
            else:
                header, body = method.split('\n', 1)
                expected = header.replace(sig, alias(sig)) + '\n' + body
                if normal(expected) != normal(new[alias(sig)]):
                    raise ValueError(f'Renamed native method body changed: {klass}.{sig}')
                if normal_wrapper(wrapper(klass, sig)) != normal_wrapper(new[sig]):
                    raise ValueError(f'Unexpected wrapper: {klass}.{sig}')
        changed.append(klass)
    for path, source in helper.items():
        if normal(source) != normal(final[path]):
            raise ValueError(f'Helper class changed: {path}')
    return {'original_classes_checked': len(original), 'helper_classes_added': len(helper),
            'changed_original_classes': sorted(changed), 'native_method_bodies': 'unchanged under renamed methods',
            'relocated_original_classes': sorted(changed), 'other_original_classes_and_methods': 'unchanged',
            'assembly_normalizations': 'explicit zero/false static values may become implicit defaults'}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input_apk', type=Path)
    parser.add_argument('work_dir', type=Path)
    parser.add_argument('--output', type=Path, help='Default: WORK_DIR/AndroidSystemIntelligence-C9-onyx.apk')
    parser.add_argument('--sdk', type=Path, default=Path(os.environ.get('ANDROID_SDK_ROOT', os.environ.get('ANDROID_HOME', str(Path.home() / 'Android/Sdk')))))
    parser.add_argument('--platform', default='android-37.0')
    parser.add_argument('--build-tools', default='36.0.0')
    parser.add_argument('--apktool', default=shutil.which('apktool') or str(Path.home() / '.local/bin/apktool'))
    args = parser.parse_args()
    module, original, work = Path(__file__).resolve().parent, args.input_apk.resolve(strict=True), args.work_dir.resolve()
    output = args.output.resolve() if args.output else work / 'AndroidSystemIntelligence-C9-onyx.apk'
    if output == original:
        parser.error('Output must not overwrite original source APK')
    original_bytes = original.read_bytes()
    if sha(original_bytes) != INPUT_SHA256:
        parser.error('Input differs from the inspected C.9 APK SHA256')
    if run([args.apktool, '--version'], capture=True).strip() != '3.0.3':
        parser.error('Exact code contract requires Apktool 3.0.3')
    android_jar = args.sdk / 'platforms' / args.platform / 'android.jar'
    build_tools = args.sdk / 'build-tools' / args.build_tools
    for tool in ('javac', 'java', 'jar'):
        if not shutil.which(tool):
            parser.error(f'Missing {tool}')
    for path in (android_jar, build_tools / 'd8', build_tools / 'aapt2', build_tools / 'zipalign'):
        if not path.exists():
            parser.error(f'Missing SDK dependency: {path}')
    sources = [module / 'src' / OWN_PACKAGE / f'{name}.java' for name in ('CalendarPolicy', 'CalendarBridge')]
    for source in sources:
        if not source.is_file():
            parser.error(f'Missing source: {source}')
    block = signing_block(original_bytes)
    work.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='build-', dir=work) as temporary:
        temp = Path(temporary)
        classes, tests, dex = temp / 'classes', temp / 'tests', temp / 'dex'
        for directory in (classes, tests, dex):
            directory.mkdir()
        run(['javac', '--release', '8', '-Xlint:all,-options', '-d', tests, sources[0], module / 'tests/CalendarPolicyTest.java'])
        policy = run(['java', '-cp', tests, 'dev.loukious.onyx.smartspacefix.CalendarPolicyTest'], capture=True)
        (work / 'policy-tests.txt').write_text(policy)
        print(policy, end='')
        run(['javac', '--release', '8', '-Xlint:all,-options', '-cp', android_jar, '-d', classes, *sources])
        own_jar = temp / 'helper.jar'
        run(['jar', '--create', '--file', own_jar, '-C', classes, '.'])
        run([build_tools / 'd8', '--release', '--min-api', '31', '--lib', android_jar, '--output', dex, own_jar])
        helper_apk = temp / 'helper.apk'
        with zipfile.ZipFile(original) as base, zipfile.ZipFile(helper_apk, 'w') as helper_zip:
            helper_zip.writestr('AndroidManifest.xml', base.read('AndroidManifest.xml'))
            helper_zip.write(dex / 'classes.dex', 'classes.dex')
        helper_decoded, decoded = temp / 'helper-decoded', temp / 'decoded'
        run([args.apktool, 'd', '--no-res', '-o', helper_decoded, helper_apk])
        helper_source = inventory(helper_decoded)
        if not helper_source or any(not path.startswith('smali/' + OWN_PACKAGE) for path in helper_source):
            raise ValueError('Helper contains classes outside the owned package')
        helper_expected = {path.replace('smali/', 'smali_classes6/', 1): text for path, text in helper_source.items()}
        run([args.apktool, 'd', '--no-res', '-o', decoded, original])
        pristine = inventory(decoded)
        if (decoded / 'smali_classes6').exists():
            raise ValueError('Original APK unexpectedly has a sixth DEX')
        shutil.copytree(helper_decoded / 'smali', decoded / 'smali_classes6')
        patches = []
        for klass in SIGNATURES:
            path = decoded / 'smali_classes2' / f'{klass}.smali'
            before = path.read_text()
            after = patch_class(klass, before)
            # classes2.dex already uses all 65536 method IDs. Move only these
            # patched definitions into the new DEX to make room for wrappers;
            # all classes still share the APK's original class loader/package.
            (decoded / 'smali_classes6' / f'{klass}.smali').write_text(after)
            path.unlink()
            patches.extend(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                               fromfile=f'original/{klass}.smali', tofile=f'patched/{klass}.smali'))
        (work / 'smali.patch.diff').write_text(''.join(patches))
        rebuilt = temp / 'rebuilt.apk'
        run([args.apktool, 'b', '-o', rebuilt, decoded])
        unaligned, aligned = temp / 'unaligned.apk', temp / 'aligned.apk'
        members = {}
        with zipfile.ZipFile(original) as base, zipfile.ZipFile(rebuilt) as built, zipfile.ZipFile(unaligned, 'w') as final:
            if len(base.namelist()) != len(set(base.namelist())):
                raise ValueError('Duplicate original ZIP members')
            for info in base.infolist():
                before = base.read(info)
                after = built.read(info.filename) if info.filename == 'classes2.dex' else patch_manifest(before) if info.filename == 'AndroidManifest.xml' else before
                target = copy.copy(info)
                if info.filename.endswith('.dex') or info.filename.startswith('lib/') and info.filename.endswith('.so'):
                    target.compress_type = zipfile.ZIP_STORED
                final.writestr(target, after)
                members[info.filename] = {'original': sha(before), 'patched': sha(after)}
            own_info = zipfile.ZipInfo('classes6.dex', date_time=(2008, 1, 1, 0, 0, 0))
            own_info.compress_type = zipfile.ZIP_STORED
            new_dex = built.read('classes6.dex')
            final.writestr(own_info, new_dex)
            members['classes6.dex'] = {'original': None, 'patched': sha(new_dex)}
        run([build_tools / 'zipalign', '-f', '-P', '16', '4', unaligned, aligned])
        output.write_bytes(insert_block(aligned.read_bytes(), block))
        run([build_tools / 'zipalign', '-c', '-P', '16', '4', output])
        with zipfile.ZipFile(output) as final:
            if set(final.namelist()) != set(members):
                raise ValueError('Final ZIP inventory mismatch')
            for info in final.infolist():
                if sha(final.read(info)) != members[info.filename]['patched']:
                    raise ValueError(f'Final ZIP member changed: {info.filename}')
                if (info.filename.endswith('.dex') or info.filename.startswith('lib/') and info.filename.endswith('.so')) and info.compress_type != 0:
                    raise ValueError(f'Compressed DEX/native member: {info.filename}')
        verification = temp / 'verification'
        run([args.apktool, 'd', '--no-res', '-o', verification, output])
        code_verification = verify_code(pristine, inventory(verification), helper_expected)
        badging = run([build_tools / 'aapt2', 'dump', 'badging', output], capture=True)
        identity = [line for line in badging.splitlines() if line.startswith(('package:', 'minSdkVersion:', 'targetSdkVersion:'))]
        if not identity or f"versionCode='{NEW_VERSION}'" not in identity[0] or f"versionName='{NEW_NAME}'" not in identity[0]:
            raise ValueError('Final APK identity parse failed')
    changed_members = [name for name, hashes in members.items() if hashes['original'] != hashes['patched']]
    if sorted(changed_members) != ['AndroidManifest.xml', 'classes2.dex', 'classes6.dex']:
        raise ValueError('Unexpected APK payload change')
    receipt = {'kind': 'Trusted ROM AIAI prebuilt; original signer metadata retained, modified contents are not Google-signed',
               'input': str(original), 'input_sha256': INPUT_SHA256, 'output': str(output), 'output_sha256': sha(output.read_bytes()),
               'version_code': NEW_VERSION, 'version_name': NEW_NAME, 'signing_block_sha256': BLOCK_SHA256,
               'identity': identity, 'changed_members': changed_members, 'code_verification': code_verification,
               'source_sha256': {source.name: sha(source.read_bytes()) for source in sources}, 'members': members}
    (work / 'rom-build-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(f'ROM prebuilt: {output}')
    print(f"SHA256: {receipt['output_sha256']}")
    print(f'Verification: {code_verification}')
    print(f"Receipt: {work / 'rom-build-receipt.json'}")

if __name__ == '__main__':
    main()
