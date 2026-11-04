#!/usr/bin/env python3
"""Sync the current ROM manifest, preserve local edits, apply Onyx patches; never build.
Usage: sync-local.py [ROM_ROOT] [--jobs 8] [--resume BACKUP_DIR]
Patch repository updates are intentionally separate: local patch development is authoritative.
"""
import argparse
from datetime import datetime, timezone
import json
import fcntl
import os
from pathlib import Path
import subprocess
import tarfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('rom', nargs='?', default=str(Path.home() / 'Android/custom-rom'))
p.add_argument('--jobs', type=int, default=8)
p.add_argument('--resume', type=Path)
a = p.parse_args()
rom = Path(a.rom).resolve()
patches = Path(__file__).resolve().parent.parent
if not (rom / '.repo').is_dir() or a.jobs < 1:
    p.error('Expected a repo workspace and positive job count')

lock = (rom / '.repo/onyx-local-sync.lock').open('w')
try:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    raise SystemExit('Another local sync is running for this workspace.')

def run(argv, cwd=rom, **kw):
    return subprocess.run(argv, cwd=cwd, check=True, **kw)

def git(project, *args):
    return run(['git', *args], cwd=project, stdout=subprocess.PIPE).stdout

backup = a.resume.resolve() if a.resume else rom.parent / 'rom-sync-backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
backup.mkdir(parents=True, exist_ok=True)
statefile = backup / 'state.json'
state = json.loads(statefile.read_text()) if a.resume else {'rom': str(rom), 'projects': [], 'phase': 'backup'}
if state['rom'] != str(rom):
    p.error('Resume directory belongs to another workspace')

def save():
    temp = statefile.with_suffix('.tmp')
    temp.write_text(json.dumps(state, indent=2) + '\n')
    temp.replace(statefile)

print(f'Backup and recovery state: {backup}', flush=True)
if state['phase'] == 'backup':
    if a.resume:
        raise SystemExit('Interrupted during backup: inspect state.json before continuing; no checkout sync was started.')
    run(['repo', 'manifest', '-r', '-o', str(backup / 'manifest-before.xml')])
    # Preserve manifest overrides as-is; repo sync updates the upstream manifest.
    with tarfile.open(backup / 'local-manifests.tar', 'w') as t:
        t.add(rom / '.repo/local_manifests', arcname='local_manifests')
    paths = run(['repo', 'list', '-p'], stdout=subprocess.PIPE, text=True).stdout.splitlines()
    # Backup every dirty project before any checkout is changed. Ignored outputs stay in place.
    for path in paths:
        project = rom / path
        if not (project / '.git').exists():
            continue  # new manifest project, not yet checked out
        if not git(project, 'status', '--porcelain'):
            continue
        if git(project, 'diff', '--name-only', '--diff-filter=U'):
            raise SystemExit(f'Unresolved conflicts in {path}; resolve before syncing.')
        dest = backup / 'projects' / path
        dest.mkdir(parents=True, exist_ok=True)
        (dest / 'tracked.patch').write_bytes(git(project, 'diff', '--binary', 'HEAD'))
        (dest / 'index.patch').write_bytes(git(project, 'diff', '--cached', '--binary'))
        untracked = git(project, 'ls-files', '--others', '--exclude-standard', '-z').split(b'\0')
        with tarfile.open(dest / 'untracked.tar', 'w') as t:
            for name in untracked:
                if name:
                    filename = os.fsdecode(name)
                    t.add(project / filename, arcname=filename, recursive=False)
        entry = {'path': path, 'head': git(project, 'rev-parse', 'HEAD').decode().strip(), 'restored': False}
        state['projects'].append(entry)
        save()
    # Stashes retain an additional copy; backup refs survive subsequent stash operations.
    for entry in state['projects']:
        project = rom / entry['path']
        git(project, 'reset', '--mixed', 'HEAD')  # also clears intent-to-add entries
        git(project, 'stash', 'push', '-u', '-m', f'onyx-sync {backup.name}')
        entry['stash'] = git(project, 'rev-parse', 'refs/stash').decode().strip()
        git(project, 'update-ref', f'refs/onyx-sync/{backup.name}', entry['stash'])
        save()
    state['phase'] = 'sync'
    save()
if state['phase'] == 'sync':
    # --force-sync handles upstream project-name migrations; no force-checkout or clean.
    run(['repo', 'sync', '-c', '-d', '--force-sync', '--no-clone-bundle', '--no-tags', f'-j{a.jobs}'])
    state['phase'] = 'restore'
    save()
if state['phase'] == 'restore':
    conflicts = []
    for entry in state['projects']:
        if entry['restored']:
            continue
        project = rom / entry['path']
        # An attempted conflicting application must be resolved manually before resume.
        if entry.get('attempted'):
            if not entry.get('conflicted', True):
                raise SystemExit(f'Failed stash application in {entry["path"]}; inspect its restore.log and backup before retrying.')
            if git(project, 'diff', '--name-only', '--diff-filter=U'):
                conflicts.append(entry['path'])
                continue
            entry['restored'] = True
            save()
            continue
        entry['attempted'] = True
        save()
        result = subprocess.run(['git', 'stash', 'apply', entry['stash']], cwd=project,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (backup / 'projects' / entry['path'] / 'restore.log').write_bytes(result.stdout)
        if result.returncode:
            entry['conflicted'] = bool(git(project, 'diff', '--name-only', '--diff-filter=U'))
            print(result.stdout.decode(errors='replace'), flush=True)
            conflicts.append(entry['path'])
        else:
            entry['restored'] = True
        save()
    if conflicts:
        raise SystemExit('Resolve restoration conflicts, then --resume this directory: ' + ', '.join(conflicts))
    state['phase'] = 'patch'
    save()
if state['phase'] == 'patch':
    # The Konoha manifest already supplies the matched kernel and modules.
    env = {**os.environ, 'SKIP_KERNEL': '1'}
    run(['bash', str(patches / 'apply.sh'), str(rom)], env=env)
    run(['bash', str(patches / 'ci/check-imports.sh'), str(rom)])
    run(['repo', 'manifest', '-r', '-o', str(backup / 'manifest-after.xml')])
    state['phase'] = 'done'
    save()
print('Sync, local-edit restoration and patch checks complete. No build was started.')
