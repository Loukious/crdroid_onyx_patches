"""Execute the rollback script with an unsupported APK before any mutation."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

SOURCE = Path(__file__).resolve().parent / 'module-template/rollback.sh'
MKSH = os.environ.get('MOSEY_TEST_MKSH') or shutil.which('mksh')
if MKSH is None:
    raise SystemExit('Set MOSEY_TEST_MKSH or install mksh to run this check.')
COMMON = '''
MOSEY_MOD=${0%/*}
MOSEY_STATE="$MOSEY_MOD/state"
MOSEY_GMS_VERSION=264630035
MOSEY_APP_VERSION=60715
mosey_init() { return 0; }
mosey_compatible() { return 0; }
mosey_app_compatible() { [ "$MOSEY_TEST_APP_COMPAT" = 1 ]; }
mosey_user_unlocked() { return 0; }
mosey_framework() { printf '%s\n' "$*" >> "$MOSEY_MOD/calls"; }
mosey_cache() { printf 'cache %s\n' "$*" >> "$MOSEY_MOD/calls"; printf 'unchanged\n'; }
mosey_log() { :; }
'''
with tempfile.TemporaryDirectory(prefix='onyx-rollback-apk-guard-') as temporary:
    root = Path(temporary)
    (root / 'state').mkdir()
    shutil.copy2(SOURCE, root / 'rollback.sh')
    (root / 'common.sh').write_text(COMMON)
    for compatible in ('0', '1'):
        process = subprocess.run([MKSH, str(root / 'rollback.sh')],
                                 env=dict(os.environ, MOSEY_TEST_APP_COMPAT=compatible),
                                 capture_output=True, text=True, timeout=10)
        if compatible == '0':
            assert process.returncode == 1
            assert not (root / 'disable').exists()
            assert not (root / 'calls').exists()
        else:
            assert process.returncode == 0, process.stderr
            assert (root / 'disable').exists()
            assert 'cache --rollback' in (root / 'calls').read_text()
print('Active APK guard rejects rollback before disabling or changing flags: PASS')
