"""Prebuilt inventory rejection and source-kernel replacement checks; no builds."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]

class PrebuiltTests(unittest.TestCase):
    def test_inventory_rejects_corruption_and_unlisted_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'prebuilt.json').write_text(json.dumps({'device':'onyx','kernel_release':'6.18.38-android17-test','modules':1}))
            (root/'Image').write_bytes(b'test image')
            (root/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in sorted(root.iterdir())))
            command=['python3',str(ROOT/'ci/verify-konoha-prebuilt.py'),str(root)]
            self.assertEqual(subprocess.run(command,capture_output=True).returncode,0)
            (root/'Image').write_bytes(b'corrupt')
            self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0)
            (root/'Image').write_bytes(b'test image');(root/'unexpected.ko').touch()
            self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0)

    def test_board_switch_removes_dependencies_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);device=root/'onyx';device.mkdir();prebuilt=root/'onyx-kernel';prebuilt.mkdir()
            (prebuilt/'prebuilt.json').write_text('{}')
            (device/'BoardConfig.mk').write_text('# Kernel\nTARGET_KERNEL_SOURCE := kernel/xiaomi/sm8735\nBOARD_KERNEL_CMDLINE := keep=1\nBOARD_BOOTCONFIG := androidboot.hardware=qcom\n# Partitions\nBOARD_BOOTIMAGE_PARTITION_SIZE := 100663296\n-include vendor/extra/BoardConfigKernel.mk\n')
            (device/'crdroid.dependencies').write_text(json.dumps([{'target_path':'kernel/xiaomi/sm8735'},{'target_path':'hardware/xiaomi'}]))
            cmd=['bash',str(ROOT/'scripts/device_xiaomi_onyx/0019-konoha-prebuilt.sh'),str(device)]
            subprocess.run(cmd,check=True,capture_output=True)
            first=(device/'BoardConfig.mk').read_text()
            subprocess.run(cmd,check=True,capture_output=True)
            self.assertEqual(first,(device/'BoardConfig.mk').read_text())
            self.assertNotIn('kernel/xiaomi/sm8735',first)
            self.assertNotIn('vendor/extra/BoardConfigKernel.mk',first)
            self.assertIn('BOARD_KERNEL_CMDLINE := keep=1',first)
            self.assertEqual(json.loads((device/'crdroid.dependencies').read_text()),[{'target_path':'hardware/xiaomi'}])

if __name__=='__main__':unittest.main()
