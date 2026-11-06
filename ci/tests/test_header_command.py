"""Parse the generated command with each supported header provider selected."""
import json
import os
from pathlib import Path
import re
import subprocess
import unittest

BP = Path(os.environ.get('ONYX_ROM_ROOT', '/nonexistent')) / 'vendor/lineage/build/soong/Android.bp'

class HeaderCommand(unittest.TestCase):
    @unittest.skipUnless(BP.is_file(), 'requires the synced vendor tree')
    def test_empty_inactive_prebuilt_path_is_valid_shell(self):
        text = BP.read_text().split('name: "generated_kernel_includes",', 1)[1]
        expression = text.split('cmd:', 1)[1].split('// Directories', 1)[0]
        command = ''.join(json.loads(s) for s in re.findall(r'"(?:[^"\\]|\\.)*"', expression))
        for headers, prebuilt, platform in [('headers.py', '', 'onyx'), ('', 'headers.tar.gz', ''), ('', '', 'onyx')]:
            values = {'TARGET_KERNEL_PORT_HEADERS': headers, 'TARGET_PREBUILT_KERNEL_HEADERS': prebuilt,
                      'TARGET_KERNEL_PLATFORM_TARGET': platform, 'KERNEL_MAKE_CMD': 'make',
                      'KERNEL_PATH': '/source', 'TARGET_KERNEL_SOURCE': 'common',
                      'KERNEL_BUILD_OUT_PREFIX': '/rom/', 'genDir': 'out/headers'}
            shell = re.sub(r'\$\((\w+)\)', lambda m: values.get(m[1], ''), command)
            result = subprocess.run(['bash', '-n'], input=shell, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

if __name__ == '__main__':
    unittest.main()
