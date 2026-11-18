# Onyx brightness KernelSU trial

The module template overlays the exact installed `services.jar` after surgical
replacement of the brightness classes, plus the two panel XML files. Its test
variant enables the existing policy directly. A verified SystemUI candidate may
also replace the exact installed `SystemUIGoogle.apk` to test brightness gesture
handling. The production ROM source keeps its resource opt-in.

This is a build-specific experiment. `compatibility.prop` and the installed-file
baseline manifest bind it to Onyx, SDK 37 and the installed ROM's exact hashes.
The payload manifest permits only `/system/framework/services.jar` and the two
`/vendor/etc/displayconfig/display_id_*.xml` files listed in `common.sh`, with
optional `/system_ext/priv-app/SystemUIGoogle/SystemUIGoogle.apk` as a fourth file.
The baseline and payload manifests must include the same paths. Archive hashes
must match the installed payload hashes, and unlisted overlay files are rejected.

The root builder supplies these files alongside the template:

- `module.prop`, with ID `onyx_stock_brightness_test`.
- `compatibility.prop`, with `ONYX_DEVICE=onyx`, `ONYX_INCREMENTAL=1794595788`
  and `ONYX_SDK=37` for this phone.
- `baseline.sha256` and `payload.sha256`, using the three or four absolute
  installed paths and ordinary `sha256sum` format.
- `archive-payload.sha256`, using relative `system/framework/services.jar` and
  `vendor/etc/displayconfig/...` paths in the module archive.
  Optional SystemUI uses
  `system/system_ext/priv-app/SystemUIGoogle/SystemUIGoogle.apk`, mapping to the
  installed `/system_ext` partition. KernelSU may normalize this into a separate
  `system_ext` root and `system/system_ext` symlink; runtime checks accept that layout.
- `assets.sha256`, covering runtime scripts and metadata, excluding itself, the
  payload entries, `customize.sh` and `README.md`. KernelSU deletes those last
  two files after installation. It should include both installed-path manifests
  and the archive payload manifest.
- The payload under canonical `system/` and `vendor/` partition directories.

The active OverlayFS MetaModule copies both payload directories into its ext4
image. The staged payload starts disabled. After installation, explicitly run
`ksud module disable onyx_stock_brightness_test` too: the normal installer clears
the current metadata directory's disable marker while staging its update. Run
`arm.sh` after host and device baseline verification; before the first reboot
this is normally under `/data/adb/modules_update/onyx_stock_brightness_test`.
It enables both the metadata directory and staged payload. Perform a full reboot.
`post-fs-data.sh` checks the artifacts
before zygote; `post-mount.sh` checks the visible mounted payload and adds a
one-shot disable marker. Its mounts remain active in that boot; an unexpected
second boot uses the original files. Preflight also detects a prior unverified
attempt, covering a failure that prevented the first post-mount hook from running.

The watchdog starts detached directly after mounting, with an independent
`/data/adb/service.d` fallback. A per-boot lock prevents duplicate watchers.
This remains available even though KernelSU skips a module's own service script
when the disable marker is set.
It allows five minutes for Android startup, checks for system-server or zygote
crashes, verifies the `Onyx sensors:` display dump marker, then awaits `accept.sh`
for up to fifteen minutes. `accept.sh` also requires enforcing SELinux and exact
mounted hashes. It enables subsequent boots only after runtime verification.
When SystemUI is included, the watchdog also rejects SystemUI Java/native crashes
and requires a running `com.android.systemui` process and a responding
`SystemUIService` client dump. The query is bounded to twenty seconds and rejects
embedded dump failures. Acceptance requires the SystemUI
verification marker from the current boot and rechecks process/service health.
The next boot requires the previous accepted SystemUI boot's health marker too.
Unrelated app crashes do not automatically reject this trial. Display-service
queries are bounded so a hung display handler cannot hang the watchdog. Arm-time
labeling uses KernelSU's trusted BusyBox to preserve the installed SELinux contexts
on the relocated ext4 payload; Android's toybox `chcon` lacks `--reference`.

Use Windows `adb.exe` for all device commands. After confirming successful
startup and the displayed runtime policy, the root task can run:

```sh
/mnt/d/platform-tools/adb.exe shell su -c \
    '/system/bin/sh /data/adb/modules/onyx_stock_brightness_test/accept.sh'
```

For rollback, the KernelSU module Action button disables this module and performs
a full reboot. The same operation is available through:

```sh
/mnt/d/platform-tools/adb.exe shell su -c \
    '/system/bin/sh /data/adb/modules/onyx_stock_brightness_test/rollback.sh --reboot'
```

If Android fails to start, the one-shot marker already disables the next trial
boot. KernelSU's safe mode, or creating
`/data/adb/modules/onyx_stock_brightness_test/disable` from root ADB/recovery before
a full reboot, also prevents the payload from mounting. No partition is flashed,
no base ART file is deleted, and rollback leaves the other modules enabled.
The state and boot/crash/display diagnostics remain under
`/data/adb/onyx-stock-brightness-test`.
