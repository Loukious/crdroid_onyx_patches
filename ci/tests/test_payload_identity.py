import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]

def varint(number):
    result = bytearray()
    while number > 127:
        result.append((number & 127) | 128)
        number >>= 7
    result.append(number)
    return bytes(result)

def field(number, value):
    if isinstance(value, int):
        return varint(number << 3) + varint(value)
    return varint((number << 3) | 2) + varint(len(value)) + value

def partition(name, data, operations=b''):
    info = field(1, len(data)) + field(2, hashlib.sha256(data).digest())
    return field(13, field(1, name.encode()) + field(7, info) + operations)

class PayloadIdentity(unittest.TestCase):
    def test_manifest_hashes_and_corruption_detection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = b'A' * 4096
            extent = field(1, 0) + field(2, 1)
            def op(offset):
                return field(8, field(1, 0) + field(2, offset) + field(3, len(data)) + field(6, extent))
            dlkm, recovery = b'D' * 4096, b'R' * 4096
            manifest = (partition('vendor_boot', data, op(0)) +
                        partition('vendor_dlkm', dlkm, op(4096)) +
                        partition('recovery', recovery, op(8192)))
            header = b'CrAU' + struct.pack('>QQI', 2, len(manifest), 0)
            archive = root / 'ota.zip'
            def invoke(blob):
                with zipfile.ZipFile(archive, 'w') as z:
                    z.writestr('payload.bin', header + manifest + blob)
                return subprocess.run(['python3', str(ROOT/'ci/verify-payload.py'), str(archive), str(root)], capture_output=True)
            result = invoke(data + dlkm + recovery)
            self.assertEqual(result.returncode, 0, result.stderr)
            metadata = json.loads((root/'payload-manifest.json').read_text())
            self.assertEqual(metadata['vendor_boot']['sha256'], hashlib.sha256(data).hexdigest())
            self.assertEqual((root/'payload_vendor_boot.img').read_bytes(), data)
            self.assertEqual((root/'payload_vendor_dlkm.img').read_bytes(), dlkm)
            self.assertEqual((root/'payload_recovery.img').read_bytes(), recovery)
            self.assertNotEqual(invoke(b'B' * 4096 + dlkm + recovery).returncode, 0)
            self.assertNotEqual(invoke(data + b'X' * 4096 + recovery).returncode, 0)
            self.assertNotEqual(invoke(data + dlkm + b'X' * 4096).returncode, 0)

if __name__ == '__main__':
    unittest.main()
