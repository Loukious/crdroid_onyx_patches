#!/usr/bin/env python3
"""Exercise actual candidate loader with the retained Android-tool fixture."""
import concurrent.futures
import hashlib
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
PRODUCTION = HERE
spec = importlib.util.spec_from_file_location('retained_driver_tests', PRODUCTION / 'test_module.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
# Only the source path used by run_shell changes. Android calls remain mocked;
# the production repository and test file stay unchanged.
module.HERE = HERE
SOURCE = (HERE / 'module-template/common.sh').read_text()
PREFLIGHT = SOURCE.split('wdr_preflight() {', 1)[1].split('wdr_replacement_running()', 1)[0]
NEW_BOOT = '47d7db1b-fce6-49e6-8785-1ab38f6c2cef'


class BootLockTests(unittest.TestCase):
    def setUp(self):
        self.fixture = module.ReloadTests()
        self.fixture.setUp()
        self.boot = (self.fixture.proc / 'sys/kernel/random/boot_id').read_text().strip()
        self.lock = self.fixture.state / ('reload-' + self.boot + '.lock')

    def tearDown(self):
        self.fixture.tearDown()

    def call(self, body='wdr_reload'):
        return self.fixture.run_shell(stage='live', body=body)

    def assert_calls(self, count):
        self.assertEqual(count, len(self.fixture.tool_calls()))
        self.assertTrue(all('-f' not in call for call in self.fixture.tool_calls()))

    def test_legacy_global_lock_is_ignored_and_preserved(self):
        old_lock = self.fixture.state / 'reload.lock'
        old_lock.mkdir()
        marker = old_lock / 'historical-receipt'
        marker.write_bytes(b'preserve interrupted old boot')
        result = self.call()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assert_calls(2)
        self.assertEqual(b'preserve interrupted old boot', marker.read_bytes())
        self.assertFalse(self.lock.exists())

    def test_old_boot_lock_and_attempt_do_not_block_new_boot(self):
        old_lock = self.fixture.state / ('reload-' + self.boot + '.lock')
        old_lock.mkdir()
        marker = old_lock / 'old-owner'
        marker.write_bytes(b'old owner stays recorded')
        attempt = self.fixture.state / self.boot
        attempt.mkdir()
        (attempt / 'replacement-loaded').write_bytes(b'old boot record')
        (self.fixture.proc / 'sys/kernel/random/boot_id').write_text(NEW_BOOT + '\n')
        result = self.call()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assert_calls(2)
        self.assertEqual(b'old owner stays recorded', marker.read_bytes())
        self.assertEqual(b'old boot record', (attempt / 'replacement-loaded').read_bytes())
        self.assertTrue((self.fixture.state / NEW_BOOT / 'replacement-loaded').exists())
        self.assertFalse((self.fixture.state / ('reload-' + NEW_BOOT + '.lock')).exists())

    def test_same_boot_lock_rejects_without_taking_or_removing_it(self):
        self.lock.mkdir()
        marker = self.lock / 'owner'
        marker.write_bytes(b'active owner')
        result = self.call()
        self.assertNotEqual(0, result.returncode)
        self.assert_calls(0)
        self.assertEqual(b'active owner', marker.read_bytes())
        self.assertFalse((self.fixture.state / self.boot).exists())

    def test_same_boot_attempt_exclusion_and_owned_lock_release(self):
        attempt = self.fixture.state / self.boot
        attempt.mkdir()
        marker = attempt / 'historical-result'
        marker.write_bytes(b'do not repeat')
        result = self.call()
        self.assertNotEqual(0, result.returncode)
        self.assert_calls(0)
        self.assertEqual(b'do not repeat', marker.read_bytes())
        self.assertFalse(self.lock.exists())

    def test_concurrent_same_boot_loader_is_excluded(self):
        ready = self.fixture.root / 'first-loader-ready'
        release = self.fixture.root / 'release-first-loader'
        body = 'wdr_preflight_base() {' + PREFLIGHT + '''
wdr_preflight_count=0
wdr_preflight() {
    wdr_preflight_count=$((wdr_preflight_count + 1))
    if [ "$wdr_preflight_count" = 1 ]; then
        touch ''' + shlex.quote(str(ready)) + '''
        while [ ! -e ''' + shlex.quote(str(release)) + ''' ]; do sleep .01; done
    fi
    wdr_preflight_base
}
wdr_reload
'''
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(self.call, body)
            try:
                deadline = time.monotonic() + 10
                while not ready.exists() and time.monotonic() < deadline:
                    if first.done():
                        self.fail('first loader ended before holding the lock: ' + repr(first.result()))
                    time.sleep(.01)
                self.assertTrue(ready.exists(), 'bounded first-loader wait expired')
                second = self.call()
                self.assertNotEqual(0, second.returncode, second.stdout + second.stderr)
                self.assert_calls(0)
                self.assertTrue(self.lock.exists())
            finally:
                release.touch()
            result = first.result(timeout=10)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assert_calls(2)
        self.assertFalse(self.lock.exists())

    def mutate_boot_on_preflight(self, invocation):
        target = self.fixture.proc / 'sys/kernel/random/boot_id'
        return 'wdr_preflight_base() {' + PREFLIGHT + '''
wdr_preflight_count=0
wdr_preflight() {
    wdr_preflight_count=$((wdr_preflight_count + 1))
    if [ "$wdr_preflight_count" = ''' + str(invocation) + ''' ]; then
        printf '%s\n' ''' + shlex.quote(NEW_BOOT) + ' > ' + shlex.quote(str(target)) + '''
    fi
    wdr_preflight_base
}
wdr_reload
'''

    def test_boot_changed_during_initial_preflight_never_unloads(self):
        result = self.call(self.mutate_boot_on_preflight(1))
        self.assertNotEqual(0, result.returncode)
        self.assert_calls(0)
        self.assertFalse(self.lock.exists())
        self.assertFalse((self.fixture.state / NEW_BOOT).exists())

    def test_boot_changed_during_final_preflight_never_unloads(self):
        result = self.call(self.mutate_boot_on_preflight(2))
        self.assertNotEqual(0, result.returncode)
        self.assert_calls(0)
        self.assertFalse(self.lock.exists())
        self.assertFalse((self.fixture.state / NEW_BOOT).exists())

    def test_missing_boot_rejects_before_acquiring_lock(self):
        (self.fixture.proc / 'sys/kernel/random/boot_id').unlink()
        result = self.call()
        self.assertNotEqual(0, result.returncode)
        self.assert_calls(0)
        self.assertEqual([], list(self.fixture.state.iterdir()))

    def test_unsafe_boot_rejects_before_acquiring_lock(self):
        (self.fixture.proc / 'sys/kernel/random/boot_id').write_text('../wrong/boot\n')
        result = self.call()
        self.assertNotEqual(0, result.returncode)
        self.assert_calls(0)
        self.assertEqual([], list(self.fixture.state.iterdir()))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == '__main__':
    before = HERE / 'test-fixtures/common-before-boot-lock.sh'
    assert sha(before) == 'd30d35dd9adcf1eb9685a7e62e255370668bf824def42baee4ba4218ed1187aa'
    assert SOURCE.split('wdr_reload() (', 1)[0] == before.read_text().split('wdr_reload() (', 1)[0]
    for interpreter in ('sh', 'bash'):
        subprocess.run([interpreter, '-n', str(HERE / 'module-template/common.sh')], check=True)
    suite = unittest.TestSuite([
        unittest.defaultTestLoader.loadTestsFromTestCase(BootLockTests),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    # Negative controls exercise the exact retained global-lock implementation
    # and a candidate with the final boot recheck removed.
    controls = {}
    candidate = HERE / 'module-template/common.sh'
    contents = candidate.read_bytes()
    negative_files = {
        'legacy-global-lock': (HERE / 'test-fixtures/common-before-boot-lock.sh').read_bytes(),
        'missing-final-boot-recheck': SOURCE.replace('''    [ "$(cat "$WDR_PROC/sys/kernel/random/boot_id" 2>/dev/null)" = "$wdr_boot" ] || {
        wdr_log 'Skipped: boot changed during final reload preflight.'; exit 1;
    }
''', '', 1).encode(),
    }
    with tempfile.TemporaryDirectory(prefix='onyx-boot-lock-negative-') as negative_directory:
        try:
            for name, content in negative_files.items():
                if content == contents:
                    raise AssertionError('negative source did not change: ' + name)
                negative_root = Path(negative_directory) / name
                (negative_root / 'module-template').mkdir(parents=True, exist_ok=True)
                (negative_root / 'module-template/common.sh').write_bytes(content)
                module.HERE = negative_root
                case = BootLockTests('test_legacy_global_lock_is_ignored_and_preserved' if name == 'legacy-global-lock'
                                     else 'test_boot_changed_during_final_preflight_never_unloads')
                negative = unittest.TestResult()
                case.run(negative)
                if len(negative.failures) != 1 or negative.errors:
                    raise AssertionError('negative control did not fail its assertion: ' + name)
                controls[name] = 'failed-as-required'
        finally:
            module.HERE = HERE
    if candidate.read_bytes() != contents:
        raise AssertionError('candidate source changed during offline review')
    report = {
        'passed': True,
        'focused_boot_lock_tests': unittest.defaultTestLoader.loadTestsFromTestCase(BootLockTests).countTestCases(),
        'total_tests': result.testsRun, 'negative_controls': controls,
        'candidate_sha256': sha(candidate), 'retained_common_sha256': sha(HERE / 'test-fixtures/common-before-boot-lock.sh'),
        'test_sha256': sha(Path(__file__)), 'fixture_sha256': sha(PRODUCTION / 'test_module.py'),
        'scope': 'Actual candidate reload and retained Android-tool fixture; concurrency, old/current boot exclusion, final boot races and unchanged failure/rollback guards. Android calls mocked.',
        'production_edits': False, 'device_changes': False,
    }
    print(json.dumps(report, indent=2))
