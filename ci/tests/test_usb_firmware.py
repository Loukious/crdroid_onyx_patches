"""Verify the device hook and shipped-OTA firmware rejection paths without a build."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('source_kernel', ROOT / 'ci/verify-source-kernel.py')
source_kernel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source_kernel)


class UsbFirmwareTests(unittest.TestCase):
    def test_device_hook_patch_replays_without_touching_other_edits(self):
        patch = ROOT / 'patches/device_xiaomi_onyx/0024-package-source-usb-wifi-firmware.patch'
        before = ('# An independent local setting\nLOCAL_SETTING := preserve\n\n'
                  '    frameworks/native/data/etc/android.hardware.wifi.xml:$(TARGET_COPY_OUT_VENDOR)/etc/permissions/android.hardware.wifi.xml \\\n'
                  '    frameworks/native/data/etc/android.hardware.wifi.aware.xml:$(TARGET_COPY_OUT_VENDOR)/etc/permissions/android.hardware.wifi.aware.xml\n\n'
                  '# Vendor\n$(call inherit-product, vendor/xiaomi/onyx/onyx-vendor.mk)\n\n'
                  '# Vendor MiuiCamera\n$(call inherit-product-if-exists, device/xiaomi/onyx-miuicamera/device.mk)\n')
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            device = directory / 'device.mk'
            device.write_text(before)
            subprocess.run(['git', 'apply', str(patch)], cwd=directory, check=True, capture_output=True)
            after = device.read_text()
            self.assertIn('LOCAL_SETTING := preserve', after)
            self.assertEqual(after.count('port/rom/firmware.mk'), 1)
            subprocess.run(['git', 'apply', '--reverse', '--check', str(patch)], cwd=directory, check=True)
            subprocess.run(['git', 'apply', '--reverse', str(patch)], cwd=directory, check=True)
            self.assertEqual(device.read_text(), before)

    def fixture(self, directory):
        source = directory / 'source'
        package = source / 'port/firmware'
        vendor = directory / 'vendor'
        blobs = []
        for index in range(16):
            name = f'rtlwifi/test-{index}.bin'
            data = bytes([index])
            packed = vendor / 'firmware' / name
            packed.parent.mkdir(parents=True, exist_ok=True)
            packed.write_bytes(data)
            blobs.append({'path': name, 'sha256': hashlib.sha256(data).hexdigest()})
        for name, data in {'README.md': b'notices', 'licenses/firmware.txt': b'license',
                           'sources/source.tar.gz': b'corresponding source'}.items():
            path = package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (package / 'manifest.json').write_text(json.dumps({'blobs': blobs}))
        (source / 'port/nethunter-native-modules.json').write_text(json.dumps({
            'wireless_firmware': [entry['path'] for entry in blobs],
            'firmware_source_archives': [{'path': 'sources/source.tar.gz',
                'sha256': hashlib.sha256(b'corresponding source').hexdigest()}]}))
        notices = vendor / 'etc/firmware-notices/onyx-usb-wifi'
        shutil.copytree(package, notices)
        return source, vendor

    def test_missing_changed_or_linked_firmware_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, vendor = self.fixture(Path(temporary))
            source_kernel.verify_firmware(vendor, source)
            blob = vendor / 'firmware/rtlwifi/test-0.bin'
            for change in ('changed', 'missing', 'linked'):
                if blob.exists() or blob.is_symlink():
                    blob.unlink()
                if change == 'changed':
                    blob.write_bytes(b'changed')
                elif change == 'linked':
                    target = vendor / 'replacement'
                    target.write_bytes(b'\0')
                    blob.symlink_to(target)
                with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'wireless firmware differs'):
                    source_kernel.verify_firmware(vendor, source)

    def test_missing_corresponding_source_or_license_is_rejected(self):
        for missing in ('licenses/firmware.txt', 'sources/source.tar.gz'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as temporary:
                source, vendor = self.fixture(Path(temporary))
                (vendor / 'etc/firmware-notices/onyx-usb-wifi' / missing).unlink()
                with self.assertRaisesRegex(ValueError, 'notice/source differs'):
                    source_kernel.verify_firmware(vendor, source)


if __name__ == '__main__':
    unittest.main()
