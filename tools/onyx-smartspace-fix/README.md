# Onyx At a Glance calendar fix

This builds the calendar correction directly into the ROM's Android System
Intelligence APK. It uses ordinary Java helpers called from the examined Google
provider. No Vector, Xposed, or separately installed fix app is required.

Ordinary timed events appear 30 minutes before the occurrence starts and remain
visible until its end. Their titles use Google's localized countdown and "now"
templates, with updates at each countdown minute and at the start boundary.
Ongoing occurrences remain ahead of upcoming ones; finished occurrences expire.
Future candidates remain available for promotion, complete CalendarEvent searches
read all pages, and timers handle window opening and expiration. Other Smartspace
features, settings, native TTL/seen filtering, and dismissals continue through the
original provider.

## Build and integration

The input is **C.9.playstore.pixel11.1009419057**, SHA256
`417c0a7aa18f7c54174bba33bf02fba623ead200f4a54cd0ce66c57d6c8fdc1a`.
The patch checkout supplies the compressed original APK under
`assets/onyx-smartspace/AndroidSystemIntelligence-C9.apk.xz`; the vendor GMS
integration hook decompresses it into ignored `tools/onyx-smartspace-fix/.work` and
invokes the builder. It does not depend on a separate audit directory or clone.

`build-rom.py` requires Java 21, Python 3, Apktool 3.0.3, Android SDK platform
`android-37.0`, and build tools `36.0.0`. For a manual build with an existing
original APK:

```bash
python3 ./build-rom.py \
    ~/Android/at-a-glance-audit-20261113/com.google.android.as.apk \
    ~/Android/at-a-glance-audit-20261113/persistent/direct-rom/build
```

Use `--sdk`, `--platform`, `--build-tools`, and `--apktool` to override tool paths.
`--output` sets an explicit APK destination. Otherwise the output is
`WORK_DIR/AndroidSystemIntelligence-C9-onyx.apk`.

The builder runs the host timing regression tests, checks exact native method
hashes, and wraps seven methods while retaining their bodies under
`onyx$original$` names. The constructor receives one initialization call after its
context field is assigned. Only `classes2.dex`, the manifest's version metadata,
and the new `classes6.dex` change. The original second DEX already uses all 65536
method IDs, so the three patched class definitions move into the sixth DEX
alongside the helper. Their package and class loader remain the same. Native
libraries, Google resources, and
all other APK member contents remain identical. The final APK is disassembled to
verify the expected wrappers, unchanged native bodies, and unchanged other
classes. Build receipts and a smali diff are saved in the selected work directory;
temporary decompile and build trees are cleaned up.

ROM integration keeps the existing `DevicePersonalizationAiAiPrebuiltPixel2026`
GMS module in `/product/priv-app`. Its `PRESIGNED` declaration needs
`LOCAL_SDK_VERSION := 37` so Make copies the prepared APK without rewriting it.
The helper belongs under `tools/`, outside automatically discovered project
scripts; the integration hook belongs under `scripts/vendor_gms/`.

## Package identity and updates

The patched prebuilt retains package `com.google.android.as` and the original
Google signing block and certificate metadata. Google did not sign its modified
contents. Android's existing trusted system-partition scan collects signer
metadata without verifying APK content digests; the ROM image supplies that
trust. The builder does not change package verification. The output is intended
for a ROM prebuilt, rather than an ordinary APK installation.

The ROM version is **17000142**, named
**C.9.playstore.pixel11.1009419057.onyx.2**. This small increment takes precedence
over the currently installed C.9 update, whose code is 17000140. PackageManager
keeps existing app data while replacing the older update's code. Equal versions
would continue using the existing `/data/app` copy.

Future Google updates with a higher version code can replace this patched APK
and remove the fix. The change does not freeze System Intelligence at an
artificial maximum version. Reapply the correction against an inspected newer
Google APK when updating the ROM prebuilt.
