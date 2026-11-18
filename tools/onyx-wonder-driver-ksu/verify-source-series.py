#!/usr/bin/env python3
"""Replay the pinned Wonder source series in a private source-only fixture."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_relative(name):
    value = Path(name)
    if value.is_absolute() or '..' in value.parts or not value.parts:
        raise ValueError('unsafe source path: ' + name)
    return value


def verify(baseline, patches, manifest):
    report = {'passed': False, 'source_only': True, 'device_changes': False,
              'kernel_or_rom_build': False, 'patches': [], 'files_verified': []}
    files = manifest['files']
    for name, expected in files.items():
        source = baseline / safe_relative(name)
        if expected['baseline_sha256'] is None:
            if source.exists():
                raise ValueError('new source already exists in baseline: ' + name)
        elif not source.is_file() or digest(source) != expected['baseline_sha256']:
            raise ValueError('accepted source baseline differs: ' + name)
    for item in manifest['patches']:
        patch = patches / safe_relative(item['name'])
        if not patch.is_file() or digest(patch) != item['sha256']:
            raise ValueError('patch digest differs: ' + item['name'])
        # Reject a patch that could write outside the enumerated source set.
        for line in patch.read_text().splitlines():
            if not line.startswith(('--- ', '+++ ')):
                continue
            header = line[4:].split('\t', 1)[0]
            if header == '/dev/null':
                continue
            components = safe_relative(header).parts[item['strip']:]
            target = Path(*components).as_posix()
            if target not in files:
                raise ValueError('patch has an unlisted source target: ' + target)
    with tempfile.TemporaryDirectory(prefix='onyx-wonder-source-replay-') as temporary:
        work = Path(temporary)
        for name, expected in files.items():
            if expected['baseline_sha256'] is None:
                continue
            destination = work / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(baseline / name, destination)
        for item in manifest['patches']:
            argv = ['patch', '--batch', '--forward', '--fuzz=0',
                    '-p' + str(item['strip']), '-i', str((patches / item['name']).resolve())]
            dry = subprocess.run(argv + ['--dry-run'], cwd=work, text=True,
                                 capture_output=True)
            if dry.returncode:
                raise ValueError('patch dry run failed: ' + item['name'] + '\n' +
                                 dry.stdout + dry.stderr)
            applied = subprocess.run(argv, cwd=work, text=True, capture_output=True)
            if applied.returncode:
                raise ValueError('patch replay failed: ' + item['name'] + '\n' +
                                 applied.stdout + applied.stderr)
            report['patches'].append({'name': item['name'], 'strip': item['strip'],
                                      'sha256': item['sha256'], 'zero_fuzz': True,
                                      'dry_run_passed': True, 'replay_passed': True})
        for name, expected in files.items():
            source = work / name
            reviewed_sha = expected.get('result_sha256', expected.get('v9_sha256'))
            if not source.is_file() or digest(source) != reviewed_sha:
                raise ValueError('replayed source differs from reviewed result: ' + name)
            report['files_verified'].append({'name': name, 'sha256': reviewed_sha})
        actual_files = {p.relative_to(work).as_posix() for p in work.rglob('*') if p.is_file()}
        if actual_files != set(files):
            raise ValueError('unexpected files in replay fixture: ' + repr(actual_files ^ set(files)))
    report['passed'] = True
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True, type=Path)
    parser.add_argument('--patches', type=Path, default=Path(__file__).parent / 'source-patches')
    parser.add_argument('--manifest', type=Path, default=Path(__file__).parent / 'source-series-v9.json')
    parser.add_argument('--receipt', type=Path)
    arguments = parser.parse_args()
    manifest = json.loads(arguments.manifest.read_text())
    report = verify(arguments.baseline, arguments.patches, manifest)
    report['manifest_sha256'] = digest(arguments.manifest)
    if arguments.receipt:
        with arguments.receipt.open('x') as destination:
            json.dump(report, destination, indent=2)
            destination.write('\n')
    print(json.dumps({'passed': report['passed'], 'patches': len(report['patches']),
                      'source_files': len(report['files_verified']),
                      'source_only': True, 'device_changes': False}))


if __name__ == '__main__':
    main()
