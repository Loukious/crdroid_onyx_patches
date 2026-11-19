"""A failed resource patch must not leave files that break a later AAPT build."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / 'apply.sh').read_text()
FUNCTION = re.search(r'^apply_patches\(\) \{\n.*?^\}', SOURCE, re.M | re.S)[0]


class PatchRejects(unittest.TestCase):
    def test_failed_resource_patch_records_failure_without_littering_resource_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            here, rom = root / 'patches-repo', root / 'rom'
            patches = here / 'patches/packages_apps_Updater'
            patches.mkdir(parents=True)
            resource = rom / 'packages/apps/Updater/app/src/main/res/values/strings.xml'
            resource.parent.mkdir(parents=True)
            original = '<resources/>\n'
            resource.write_text(original)
            (patches / '0001-conflict.patch').write_text(
                '--- a/app/src/main/res/values/strings.xml\n'
                '+++ b/app/src/main/res/values/strings.xml\n'
                '@@ -1 +1 @@\n-not-this-resource\n+changed-resource\n')
            script = '''set -uo pipefail
KONOHA_SOURCE_BUILD=0
fail=0 applied=0 already=0
declare -A PROJECT=([packages_apps_Updater]=packages/apps/Updater)
red() { printf '%s\\n' "$*"; }
grn() { printf '%s\\n' "$*"; }
ylw() { printf '%s\\n' "$*"; }
''' + FUNCTION + '\napply_patches\n[[ "$fail" = 1 ]]\n'
            result = subprocess.run(['bash', '-c', script], text=True, capture_output=True,
                                    env={**os.environ, 'HERE': str(here), 'ROM': str(rom)})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('FAILED', result.stdout)
            self.assertEqual(resource.read_text(), original)
            self.assertEqual(list(resource.parent.iterdir()), [resource])


if __name__ == '__main__':
    unittest.main()
