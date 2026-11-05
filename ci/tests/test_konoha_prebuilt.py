"""Prebuilt inventory rejection and source-kernel replacement checks; no builds."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import tarfile
import unittest

ROOT=Path(__file__).resolve().parents[2]

class PrebuiltTests(unittest.TestCase):
    def test_uapi_rejects_mismatched_source_and_missing_qualcomm_header(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            revision='a'*40
            names=['linux/msm_ipa.h','linux/ion.h','linux/msm_ion.h','linux/msm_ion_ids.h',
                   'asm/signal.h','asm-generic/signal.h','linux/eventpoll.h']
            def write_bundle(source, headers):
                archive=root/'kernel-uapi-headers.tar.gz'
                with tarfile.open(archive,'w:gz') as tar:
                    for name in headers:
                        info=tarfile.TarInfo('usr/include/'+name);info.size=1
                        tar.addfile(info,io.BytesIO(b'\n'))
                digest=hashlib.sha256(archive.read_bytes()).hexdigest()
                receipt={'source_revision':source,'archive_sha256':digest,'headers':len(headers)}
                (root/'headers.json').write_text(json.dumps(receipt))
                meta={'device':'onyx','kernel_release':'6.18.38-test','modules':1,'source_revision':revision,
                      'uapi_headers':{'archive':archive.name,'receipt':'headers.json','sha256':digest,
                                      'source_revision':revision,'headers':len(headers)}}
                (root/'prebuilt.json').write_text(json.dumps(meta))
                (root/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n'
                    for p in sorted(root.iterdir()) if p.name!='SHA256SUMS'))
            command=['python3',str(ROOT/'ci/verify-konoha-prebuilt.py'),str(root)]
            write_bundle(revision,names)
            self.assertEqual(subprocess.run(command,capture_output=True).returncode,0)
            write_bundle('b'*40,names)
            self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0)
            write_bundle(revision,names[1:])
            self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0)

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
