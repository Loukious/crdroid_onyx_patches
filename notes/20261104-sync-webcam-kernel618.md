# Local sync, USB webcam, and Linux 6.18 integration study

No ROM or kernel compilation was requested or started for this work.

## Checkout and automation

The ROM is Evolution X `cnb` (Android 17), with crDroid Onyx 17.0 device,
kernel and vendor projects, plus local MoWA manifest overrides. The patch
repository is `evolution-cnb` and has both local commits and uncommitted work;
it is intentionally not reset to its remote branch.

`ci/crave-build.sh` exists, including `SYNC_ONLY=1`, but its early reset/clean
and replacement of local manifests make it inappropriate for this workstation.
It also configures a build environment and stages the stable kernel by default.

Use the new executable for local maintenance:

```bash
~/Android/crdroid_onyx_patches/ci/sync-local.py ~/Android/custom-rom --jobs 8
```

It snapshots the pinned manifest, local manifests, binary tracked diffs, index
diffs, and untracked files outside the workspace; stashes local changes; syncs
the current manifest; restores local changes; applies the patch bundle; and runs
the import checker. It never invokes envsetup, breakfast, make, mka or Bazel.
It preserves ignored build outputs and the already staged kernel Image.
`--force-sync` accommodates manifest repository-name migrations; it does not use
`--force-checkout` or `git clean`. Stashes are retained, with additional
`refs/onyx-sync/<timestamp>` references. The backup directory is printed first.

A sync or restore failure stops the operation. Resume a completed backup with:

```bash
~/Android/crdroid_onyx_patches/ci/sync-local.py ~/Android/custom-rom \
  --resume ~/Android/rom-sync-backups/TIMESTAMP
```

Local changes that conflict with upstream need review before patching can
complete. The script uses the local patch repository as the source of truth;
fetch/reconcile its branch separately when publishing or importing patch updates.

## Device as webcam

AOSP reference: https://source.android.com/docs/core/camera/webcam

The source-level enabling change is already carried by
`patches/device_xiaomi_onyx/0016-enable-device-as-webcam.patch`:
`properties/vendor.prop` sets `ro.usb.uvc.enabled=true`. Before that change,
Onyx explicitly set it false. Settings and the QTI USB gadget HAL consult this
property. A kernel-only update cannot change this read-only ROM property.

Existing pieces verified:

- `build/make/target/product/handheld_system.mk` includes `DeviceAsWebcam`.
- `vendor/qcom/opensource/usb/hal/UsbGadget.cpp` supports UVC and UVC+ADB,
  maps the gadget function to `uvc.0`, and reads `ro.usb.uvc.enabled`.
- `vendor/qcom/opensource/usb/etc/init.qcom.usb.rc` creates `uvc.0` and
  configures formats/resolutions through `vendor.usb.uvc.function.init=1`.
  Its companion shell script detects creation of that function.
- `system/sepolicy/private/device_as_webcam.te` permits camera service access,
  property reads, and read/write access to the video device nodes.
- The actual existing experimental artifact
  `konoha-android17-6.18-port-20261031/artifacts/native-hvc-battery-20261104T105521Z/gki/`
  has `CONFIG_MEDIA_SUPPORT=y`, `CONFIG_VIDEO_DEV=y`, `CONFIG_USB_F_UVC=y`,
  and `CONFIG_USB_CONFIGFS_F_UVC=y`. UVC is built in, not a missing module.
- The existing local `system/priv-app/DeviceAsWebcam/DeviceAsWebcam.apk` is present.
- The local staged vendor build.prop already contains the true property;
  this does not prove the installed ROM contains it.
- The ADB descriptor BCD correction is also already carried in the patch set;
  it is separate from enabling the webcam service.

No additional missing source component was identified. No ADB device was
connected during inspection. Streaming, camera selection, service startup and
USB-host negotiation remain runtime checks, and success cannot be claimed.
After installing a ROM containing the patch, inspect:

```bash
adb shell getprop ro.usb.uvc.enabled
adb shell pm path com.android.DeviceAsWebcam
adb shell getprop vendor.usb.uvc.function.init
adb shell getprop sys.usb.config
adb shell getprop sys.usb.state
```

Select Webcam in USB settings, then test video on the host with and without
ADB, both cameras, disconnect/reconnect, rotation and camera switching. If it
fails, collect logcat (DeviceAsWebcam/UsbGadget/camera), kernel UVC logs and
SELinux denials before changing policy. Do not add broad camera policy rules
without an observed denial. AOSP also provides webcam implementation tests.

## Where the 6.18 kernel really lives

`~/Android/konoha-kernel-gki` currently checks out the 6.6 branch
`upstream/android15-6.6-lts-20261030`. Its worktree
`~/Android/konoha-6.18-port-control` has `port/android17-6.18-onyx`.
The materialized current port is `~/Android/konoha-android17-6.18`
(`common/`, `modules/`, `port/`), with automation in
`~/Android/konoha-android17-6.18-ci`. The active development/build workspace is
`~/Android/konoha-android17-6.18-port-20261031`.

The clean published port README describes the initial 6.18.33 / 318-module
baseline. Later local development is larger: the inspected existing native-HVC
bundle reports `6.18.38-android17-5-maybe-dirty-4k`, 468 unique modules and
497 catalog entries. Therefore select an exact accepted source/artifact; do
not infer the current booted kernel from the old repository directory name,
the README baseline, or the newest diagnostic filename.

## Integration recommendation: consume a matched prebuilt artifact set

The current `vendor/extra/BoardConfigKernel.mk` sets
`TARGET_OVERRIDE_KERNEL_BIN` and deliberately retains `FULL_KERNEL_BUILD`.
That is a 6.6 workflow: compile crDroid's modules/DTBs and substitute the stable
Kono-Ha Image. It cannot be reused with a Linux 6.18 Image. 6.6 vendor modules
are not compatible with the 6.18 kernel ABI, symbol CRCs and changed interfaces.

The most direct way to stop building the crDroid kernel during every ROM build
is to build Konoha independently, then consume a versioned, checksummed package:

1. Pin a Konoha source commit, KernelSU commit, toolchain, config, and artifact
   digest. Use one successful artifact for Image, all GKI/vendor modules and
   device trees. Keep Module.symvers and module verification reports for audit.
2. Stage `Image`, DTB(s), `dtbo.img`, and modules partitioned into
   `system_dlkm`, `vendor_dlkm`, and vendor ramdisk, with validated load order,
   dependency closure, blocklists and recovery load lists. Existing
   `assemble_module_bundle.py` / `assemble_first_stage.py` and packaging reports
   already encode much of this experimental work. Reconcile their diagnostic
   serial loaders with the ROM's normal module loader before adopting them.
3. Change the Onyx kernel block (or a final included override) to use
   `TARGET_PREBUILT_KERNEL` plus `TARGET_FORCE_PREBUILT_KERNEL := true`.
   Replace the Image-only vendor/extra hook for this mode. Supply
   `BOARD_PREBUILT_DTBIMAGE_DIR` and `BOARD_PREBUILT_DTBOIMAGE` from the same
   artifact; remove source-driven DT merge generation for the prebuilt mode.
4. Set `BOARD_SYSTEM_KERNEL_MODULES`, `BOARD_VENDOR_KERNEL_MODULES`,
   `BOARD_VENDOR_RAMDISK_KERNEL_MODULES` and their corresponding load/recovery
   variables to the staged 6.18 modules. Replace the device tree's 6.6-derived
   `first_stage_modules`, `gki_modules`, and `kunit_modules` calculations.
   Check the Android make core's copy/depmod rules and avoid duplicate rules
   from the old source-kernel packaging path.
5. Preserve the 6.18 DT fixes (PMIC inventory, USB/IPA interconnect, SCMI SRAM,
   audio, WCN control and other port overlays). A stock 6.6 DTB is insufficient.
   Preserve non-diagnostic boot arguments from `port/boot-parameters.txt`,
   currently `android_arch_task_struct_size=512 sched_proxy_exec=0`.
   Do not copy panic-on-warning/debugging arguments from diagnostic reports.
6. Keep the ROM's boot/vendor_boot/init_boot/recovery ramdisks, fstab, firmware,
   signing and AVB/OTA metadata current. Let Android generate these partition
   images from matched staged inputs. Existing experimental images embed old
   ROM metadata and diagnostic settings; do not ship them wholesale in a new
   OTA. Verify recovery's module availability too.
7. Remove the 6.6 WLAN ABI-prep / stable-release symvers path in this mode.
   Use the WLAN module built by the 6.18 port with its matching symvers; do
   not overlay the 6.6 driver and attempt to load it into 6.18.
8. Validate artifact hashes, ARM64 Image header, common vermagic, extended /
   classic CRC verification, load-list coverage, depmod closure, DT IDs and
   partition sizes before any build. Then perform a fresh-output ROM build and
   boot/hardware testing when explicitly requested. Existing `out/` contains
   6.6 artifacts and cannot be evidence that 6.18 packaging is correct.

An alternative is a native Kleaf integration through
`TARGET_KERNEL_PLATFORM_TARGET`; Evolution's kernel.mk already has such a
path. It expects a `kernel/platform/kernel-<version>` workspace and a `_dist`
target with a particular flat output contract. The current Konoha port instead
builds `//common:kernel_aarch64` plus `//onyx:platform_modules`, verifies CRCs,
and separately builds corrected DTBs. An adapter/dist target and manifest
integration would be required. Prebuilt consumption is the smaller first step.

This study does not activate 6.18 packaging or claim an unbuilt configuration
is bootable. The sync script explicitly skips stable-kernel downloads so it
cannot silently replace experimental work with the 6.6 release.

## Completed maintenance validation

The 2026-11-04 sync completed for 1270 manifest projects; 115 project revisions changed compared with the captured pre-sync manifest. Local manifests were fast-forwarded with identical MoWA overrides retained. The local patch bundle incorporates newer remote content while retaining local modifications; its Git branch history was not rewritten.

The Evolver restoration conflict was resolved using the newer isolated custom resource patches. Patch application, modified XML parsing and the 46-import symbol check passed. A second patch application passed with the WLAN overlay already current. An isolated fixture verified preservation of a tracked edit and an untracked file across an upstream update. No unresolved Git conflicts remain. No compilation was performed.

Recovery snapshots: `~/Android/rom-sync-backups/20261104T193116Z/`. Operation logs: `~/Android/rom-sync-backups/20261104-sync/`. The staged kernel Image SHA-256 remains `e6af4c60e0820aeb48d632cceb7f9a77f86727bc8341e80f8656b89fbbbc1d38`.

## Connected-phone follow-up

The phone is accessible using Windows ADB at `/mnt/d/platform-tools/adb.exe`
(the Linux/WSL ADB server does not see it). Live checks confirm kernel
`6.18.38-android17-5-maybe-dirty-4k`, the installed DeviceAsWebcam APK,
`vendor.usb.uvc.function.init=1` and an existing configfs `uvc.0` function.
However, both the live property and `/vendor/build.prop:217` had
`ro.usb.uvc.enabled=false`. This directly explains the missing Settings option:
`UsbBackend` reads `UsbManager.isUvcSupportEnabled()`, which reads that property.

Applied a nonpersistent test override using KernelSU's
`/data/adb/ksu/bin/resetprop ro.usb.uvc.enabled true`; verified the property now
reads true and stopped Settings to clear its cached UVC capability. No USB
function switch, camera stream, reboot, module installation or build was done.
The user should reopen USB preferences and select Webcam to test it. The
installed vendor property is unchanged, so a normal reboot restores false.
The already-carried source patch makes this permanent in a rebuilt ROM.

## New repository follow-up: bundling already exists

Checked the live `Loukious/konoha-android17-6.18` CI README and automation.
The published documentation now describes accepted Linux 6.18.38 with 391
platform modules, 5,042 materialized source/build files, and a matched phone
package of 471 total modules including modules outside the platform catalog.
The earlier 318-module description above came from the stale local source
checkout and is superseded by this repository state.

`port/build.py` builds the GKI and complete platform catalog, exports GKI and
platform outputs plus module staging archives, and builds the corrected device
trees. `ci/export_artifacts.py` archives the complete artifact directory as
`konoha-gki-and-modules.tar.gz`; ABI exports, `release.json` and SHA256SUMS bind
it to exact inputs. `ci/verify_artifacts.py` checks complete platform inventory,
module hashes/vermagic, source pins, KernelSU and both device-tree variants.
`ci/publish_release.py` already implements publication of the complete bundle.

Local development packaging reports also show that partitioning modules into
vendor ramdisk, system_dlkm and vendor_dlkm has already been done. Therefore
module bundling does not need to be reinvented. The remaining ROM work is a
consumer/staging adapter and BoardConfig/packaging changes that use these
matched outputs instead of the source-built crDroid kernel/module/DT outputs.
Preserve existing partition/load-list knowledge and validate it against the
exact accepted artifact, including GKI/ROM modules outside the platform catalog.

At inspection the public releases list was empty and Actions build run
41893930367 was in progress. No build or workflow was triggered by this review.

## Activated after user approval

The Konoha integration is now active, superseding the earlier study/draft status.
The active local manifest tracks `evolution-cnb-konoha618` and pins prebuilt
commit `92dffd15e2099e2d57c70827a9e56a7f5d62f6a6` from
`Loukious/konoha-android17-6.18:prebuilt-onyx`. The published matching patch
branch is `Loukious/crdroid_onyx_patches:evolution-cnb-konoha618`. Crave's
main workflow now defaults to it. All 471 unique modules, the 6.18.38 Image,
corrected device trees, ABI and config sync as one pinned project.
The four source-kernel/WLAN projects are absent; their old local checkouts and
changes were archived under `~/Android/rom-sync-backups/konoha-activation-20261104T200158Z`.

Real prebuilt sync, hashes, module CRCs/vermagic, exact source snapshots,
manifest/XML parsing, import checks and repeat configuration checks passed.
No ROM/kernel compilation, partition image generation, workflow dispatch or
flashing was done. New ROM packaging still needs build/runtime validation.
See `~/Android/konoha-rom-integration/README.md` and that directory's logs.
