# Evolution X 17 `onyx` patch set

Everything I carry on top of upstream Evolution X for the POCO F7 (`onyx`),
kept as patches so the tree can be `repo sync`'d freely and re-patched
afterwards. Driven by `apply.sh`.

```sh
git clone -b evolution-cnb-konoha618 https://github.com/Loukious/crdroid_onyx_patches /tmp/patches
/tmp/patches/apply.sh /path/to/rom
```

The repo name still says `crdroid` because renaming it would break every URL
that references it; the contents target Evolution X `cnb` / Android 17. The
crDroid-era set is preserved on the `crdroid-16.0` branch.

`apply.sh` is **idempotent** — it reverse-checks each patch first and skips ones
already applied — and exits non-zero on a genuine failure so a build stops
rather than shipping a half-patched ROM.

The PermissionController and TrickyStore fixes additionally inspect their
target code before applying. An existing exemption or corrected current-user
lookup is skipped, as is a removed TrickyStore implementation. An unresolved
patch conflict still stops the build. See [guard behavior and validation](notes/userspace-identity-fixes.md).

| env | effect |
|---|---|
| `KERNEL_RELEASE_TAG` | konoha release to take the kernel Image from (default: latest) |
| `SKIP_KERNEL=1` | don't fetch/stage the kernel Image |
| `SKIP_FIRMWARE=1` | don't overlay the firmware blobs |
| `SKIP_WLAN=1` | don't overlay the wlan driver fork over sm8735-modules |
| `GITHUB_TOKEN` | used for the release API if the kernel repo is private |

## Key carried features

**Gesture navigation space** — an extra settable inset below the gesture pill.
`frameworks/base` (`Settings.java`, `DisplayPolicy.java`) plus a UI half that is
split across two projects for a reason that is not obvious: the `ListPreference`
sits in `packages/apps/Settings` (`res/xml/gesture_navigation_settings.xml`) but
its strings and arrays sit in `packages/apps/Evolver`. That resolves because
Evolution X compiles Evolver *into* the Settings APK — `Settings/Android.bp`
lists `Evolver/res` in `resource_dirs` and passes
`--extra-packages org.evolution.settings` — so an `@string` reference crosses the
project boundary at build time. Put the strings in Settings' own `res/values`
instead and they are simply the wrong file to edit; put the preference in an
Evolver screen and it lands in the wrong menu. There is no Java: Evo's
`org.evolution.settings.preferences.SystemSettingListPreference` persists the
value to `Settings.System` itself.

**LHDC A2DP codec** — Android 17 carries the reduced V5/QTI-offload port in
`packages/modules/Bluetooth`, the QTI Bluetooth Audio AIDL definitions in
`vendor/qcom/opensource/interfaces`, the `lhdc_codec_support` aconfig value in
`build/release`, and the Onyx properties/blob fixups in `device/xiaomi/onyx`.
The old Android 16 aptX Adaptive/LHDCv2/LHDCv3/QHS source-list additions are not
carried because those source files do not exist in the Android 17 Bluetooth tree
and are not required for the V5 path.

**USB webcam and ADB descriptors** — Onyx enables `ro.usb.uvc.enabled`, the
flag read by both Settings and the QTI USB gadget HAL. The existing ROM includes
DeviceAsWebcam and UVC configfs setup. The ADB daemon also encodes both Microsoft
OS descriptor versions as 16-bit BCD `0x0100` (1.00), avoiding FunctionFS version
warnings. The corrected ADB binary and vendor property artifact build locally;
deploying these changes requires a rebuilt ROM. Webcam streaming and the
corrected descriptors have not yet been tested on the phone. Kernel-only images
do not include either ROM change.

**Modem networking on newer kernels** — Onyx patch `0020` translates
`vendor_nicmd`’s existing route and IPsec netlink permissions into explicit
message grants. This restores creation of the modem data interfaces and stops
the demonstrated modem retry/wakeup loop with `netlink_xperm` enabled.
SELinux remains enforcing. See [the validation notes](notes/nicmd-netlink.md).

**Wakeup statistics** — Onyx patch `0021` labels the FSA4480 USB-C audio
switch's wakeup subtree as `sysfs_wakeup`. This lets `system_suspend` read its
statistics using existing platform permissions and removes the corresponding
SELinux denials. The label covers dynamically numbered wakeup nodes. It takes
effect with a rebuilt ROM; it does not change WLAN wakeup behavior.

**Battery settings backup** — Settings patch `0003` handles absent optional
build metadata without throwing a `NullPointerException`. It deletes absent
metadata entries from the backup and preserves valid empty and UTF-8 values.
The failure was found in the phone's backup logs and confirmed in unchanged
[AOSP source](https://android.googlesource.com/platform/packages/apps/Settings/+/7c598253ff60f06f8e6fe046f18fd88e9daa72d3/src/com/android/settings/fuelgauge/BatterySettingsStorage.java#298).
The patch includes a Robolectric regression test and takes effect after a
patched ROM is built and installed. Google's separate transport rejections
are not addressed by this change.

**PermissionController resource access** — bionic patch `0001` exempts only
`com.android.permissioncontroller` from Evolution's ROM hiding. The permission
service can load the Lineage resource APK during backup; other processes keep
the existing hiding rules.

**TrickyStore caller identity** — framework patch `0011` resolves the foreground
user as `system_server`, then restores the incoming Binder identity before the
remaining authorization checks. Caller UID, user restrictions, package targets
and SKIP exclusions are preserved. Both fixes require a patched ROM install.

**Notification rendering and history** — framework patch `0012` moves blur
initialization to attachment on the main thread, preserving background row
inflation. Patch `0014` rebuilds the notification-history string pool before
saving and reuses one sorted pool for serialization.

**QS Wi-Fi usage** — framework patch `0013` declares SystemUI's required
per-network usage permissions, checks access before querying, and labels
aggregate fallback totals as Wi-Fi instead of attributing them to one SSID.

**Radio region lookup** — Onyx patch `0022` gives
`ro.miui.customized.region` an exact system_ext property context and grants
`rild` read access to that type. It preserves the property's value/default
and forbids vendor writes. These fixes require a new ROM installation; see
[the source rationale and validation](notes/log-derived-rom-fixes.md).

**Audio diagnostic queues** — Onyx patch `0023` installs the memory-logger
configuration required by the selected Qualcomm PAL/AGM binaries. The existing
Qualcomm `sun` XML is byte-for-byte identical to both stock Global 3.0.303 and
China 3.0.305. This restores queue initialization after the phone logs exposed
the missing file; see [stock comparison and validation](notes/audio-memlogger.md).

**Bluetooth attribution** — Bluetooth patch `0002` declares the existing
`BatteryService` and `BassClient` attribution tags and supplies readable labels.
This preserves profile-specific AppOps accounting and fixes the observed
undeclared-tag errors. It requires a rebuilt Bluetooth module/ROM; see
[scope and validation](notes/bluetooth-attributions.md).

**Fingerprint cancellation** — Xiaomi hardware patch `0001` removes the
adapter's extra cancellation callback. A successful legacy HAL request is
acknowledged immediately; its completion still arrives through the vendor
notification path. This fixes duplicate completion without changing fingerprint
routing or authentication policy. It requires a rebuilt fingerprint service/ROM;
see [the HAL contract and regression checks](notes/fingerprint-cancellation.md).

**Home double-tap sleep** — framework patch `0015` stops the home-screen
gesture monitor while the notification shade or Quick Settings is open. This
prevents rapid Caffeine tile taps from putting the phone to sleep, clears
pending gestures when the shade opens, and preserves normal home double-tap.
It requires a rebuilt SystemUI/ROM; see
[the cause and regression checks](notes/home-double-tap-shade.md).

## Layout

The Secure Spaces work in `custom-rom` adds framework patches
`0003-secure-spaces-full-user-type` through
`0010-secure-space-fingerprint-routing`, Settings patch
`0002-secure-spaces-management`, the keystore/vold companion patches, and a
lineage-sdk user-switch observer acknowledgement patch. The service-side routing
API preserves native credential verification, carries per-user outcomes, and
issues a one-use handoff capability. Settings requires owner authentication
before disclosing space names and counts. The current stack includes the native
key-erasure/duress path, shared-hardware lockscreen fingerprint routing,
first-touch routing fences, anonymous user-switch transition handling, the
main-thread bouncer fix, and a dedicated routed fingerprint success haptic. The
The previous NXP NFC teardown-race workaround has been retired to
`retired/hardware_nxp_nfc`: upstream LineageOS commit 66ef2f3 (2026-10-04)
reverted the problematic f032114 teardown fix responsible for intermittent
NFC logspam and battery drain. Do not reapply the workaround on the new base.
Post-flash runtime validation is still required for NFC and the routed fingerprint haptic. See
[`SECURE_AUTH_IMPLEMENTATION_NOTES.md`](../SECURE_AUTH_IMPLEMENTATION_NOTES.md)
for scope and validation. The Android 17 focused integration build passes, and
the full `mka evolution -j12` product build completed successfully on
2026-09-29. It produced
`EvolutionX-17.0-20260928-onyx-12.2-Unofficial.zip` (5,295,639,080 bytes,
SHA-256 `782c20f639771dbbcbb43eb1145cb66cec9b3089a634de0c6556d1860df3093a`).

One directory per git project, project path with `/` → `_`. Patches are
generated with `git add -N` first, so a patch *creates* new files rather than
needing them tracked separately.

```
patches/bionic/                               0001-exempt-permissioncontroller-from-rom-hiding
patches/build_release/                        0001-lhdc-aconfig-flag
patches/device_xiaomi_onyx/                   0001-vendor-extra-kernel-hook
                                              0002-release-config-bp4a
                                              0003-lhdc-aptx-props-and-blob-fixups
                                              0005-firmware-g303-cn305-hybrid
                                              0016-enable-device-as-webcam
                                              0022-label-radio-customized-region-property
                                              0023-install-audio-memory-logger-config
patches/external_iw/                         0001-vendor-nested-data-option
patches/frameworks_base/                      0001-gesture-navbar-space
                                              0003-secure-spaces-full-user-type
                                              0004-authentication-user-identity
                                              0005-secure-space-credential-router
                                              0006-secure-space-public-switcher-privacy
                                              0007-secure-auth-key-erasure
                                              0008-secure-auth-duress-verifier
                                              0009-secure-space-entry-coordinator
                                              0010-secure-space-fingerprint-routing
                                              0011-trickystore-current-user-identity
                                              0012-fix-notification-blur-inflation-thread
                                              0013-fix-wifi-data-usage-query
                                              0014-pool-notification-history-strings
                                              0015-exclude-shade-from-home-double-tap-sleep
retired/hardware_nxp_nfc/                     0001-fix-client-thread-teardown-race (NOT applied)
patches/hardware_xiaomi/                      0001-fix-fingerprint-cancel-completion
patches/lineage-sdk/                          0001-secure-space-user-switch-observer-acks
patches/packages_apps_Evolver/                0001-gesture-navbar-space-ui
patches/packages_apps_Settings/               0001-gesture-navbar-space-ui
                                              0002-secure-spaces-management
                                              0003-battery-backup-null-metadata
patches/packages_apps_Updater/                0001-self-hosted-ota-url
patches/packages_modules_adb/                 0001-fix-functionfs-os-descriptor-bcd-version
patches/packages_modules_Bluetooth/           0001-lhdc-v5-qti-offload
                                              0002-declare-profile-attributions
patches/system_security/                      0001-secure-auth-biometric-user-scope
patches/system_vold/                          0001-secure-auth-key-erasure
patches/vendor_gms/                           0001-keep-aosp-dialer
patches/vendor_lineage/                       0001-kernel-bin-override
patches/vendor_qcom_opensource_interfaces/    0001-lhdc-aidl
retired/vendor_xiaomi_onyx/                   0001-firmware-sha1s-g303-cn305-hybrid (NOT applied)
```

The `external/iw` patch adds `[--nested]` after the vendor OUI and subcommand
for `send`, `recv`, and `recvbin`. It sets `NLA_F_NESTED` on the vendor-data
container for commands such as Qualcomm CFR, whose driver declares a Netlink
attribute policy. Commands without the option continue to send raw bytes.
For example: `iw dev wlan0 vendor send 0x001374 0xad --nested settings.bin`.
The file, stdin (`-`), and hexadecimal-byte input modes all remain supported. The
2026-10-09 local `m iw -j8` build passed. An ADB test on the flashed Onyx
confirmed all three input modes across send/recv/recvbin, preserved raw-mode
rejection for CFR, checked malformed/missing input, and collected 94 fresh
successful CFR records with valid record boundaries and trailers.

Most patches are generated from the working-tree diff. Secure Spaces is
intentionally committed in local feature commits and mirrored in the user's
forks, so `gen-patches.sh` generates those patches from pinned, audited
base/end commit ranges. This captures the committed feature without sweeping in
unrelated dirty gesture-navigation or Settings storage changes. The generator
also refuses to run when a managed source repo already has staged work, and it
updates only patch files it owns instead of deleting the whole patch directory.

## Build identity

Nothing to patch. `vendor_evolution/config/version.mk` has
`EVO_BUILD_TYPE ?= Unofficial`, so an unofficial build is what you get by
default, and the zip comes out
`EvolutionX-17.0-<date>-onyx-12.2-Unofficial.zip`.

There is no maintainer preference in Evolution X's Settings at all — every
`maintainer` hit in that tree is `PrivateSpaceMaintainer`, and the name only
reaches the OTA JSON server-side via
`vendor_evolution/build/tools/createjson.py`. So the crDroid-era trio of
identity patches (`maintainer-from-prop`, `unofficial-buildtype`, and the
`ro.crdroid.*` props in `vendor/extra`) has no target here and is gone.

**OTA source** — `packages_apps_Updater/0001` still exists, and it is the one
piece of that group worth keeping. It repoints `updater_server_url` at
[`ota/`](ota/) in this repo. Evolution X does not publish `onyx`
(`Evolution-X/OTA` has no `onyx.json`), so the stock URL is a 404 today — but if
that ever changes, an unmodified Updater would offer an official Evo weekly as
an update to this build and flashing it would take the patch set, the LHDC codec
and the Kono-Ha kernel with it. See that directory's README.

## What `apply.sh` does beyond patching

**Firmware overlay.** `vendor/xiaomi/onyx` syncs from crDroid's upstream GitLab
(4 GB, hosted free by them). Only the ~350 MB that differs — Global
OS3.0.303.0 `radio/` images with the modem pair replaced by China
OS3.0.305.0, plus the two LHDC byte-patched blobs — lives in
[`proprietary_vendor_xiaomi_onyx-firmware`](https://gitlab.com/Loukious/proprietary_vendor_xiaomi_onyx-firmware),
synced to `vendor/xiaomi/onyx-firmware` and copied over the top here. The two
images above every host's 100 MB plain-blob limit (`modem.img` 137 MB,
`modemfirmware.img` 128 MB) are Git LFS objects on GitLab — 10 GB free storage,
no bandwidth metering — stored whole, with every file carrying a `.sha256`
sibling that `apply.sh` verifies (which also catches an unfetched LFS pointer).

Forking the 4 GB vendor repo was the obvious alternative and is a trap: its
history holds several revisions of the 137 MB `modem.img`. The overlay costs
~350 MB and needs `repo init --git-lfs`, which Evo's own `vendor_gms` already
requires anyway.

**WLAN driver overlay.** The wlan driver the ROM ships is
[`Loukious/vendor_qcom_opensource_wlan`](https://github.com/Loukious/vendor_qcom_opensource_wlan)
(`onyx-v-oss-monitor-direct-konoha-abi`): MiCode's qcacld with the annibale→onyx port plus
monitor mode and direct packet injection. It is synced standalone to
`kernel/xiaomi/onyx-wlan` (repo cannot nest a project inside `sm8735-modules`)
and `apply.sh` rsyncs its four driver dirs — `fw-api`, `platform`,
`qca-wifi-host-cmn`, `qcacld-3.0` — over the `sm8735-modules` copies, which the
build then compiles as `qca_cld3_wcn7750.ko` into `vendor_dlkm` exactly like the
stock driver. The fork carries the sm8735-modules tree build wiring itself
(`sun_gki_defconfig` includes, `USE_EXTERNAL_CONFIGS`, the
`sun_gki_wcn7750` profile, `-D__ANDROID_COMMON_KERNEL__`), so the overlay needs
no Makefile surgery on this side. `SKIP_WLAN=1` skips the overlay.

**Wi-Fi CFR capture.** Device patch `0015-enable-wifi-cfr.patch` sets
`cfr_disable=0` in the WCN7750 vendor INI. The WLAN fork enables streamfs
capture output and uses the single DBR ring supported by WCN7750 firmware.
Its ABI preparation enables kernel relay and debugfs support and rejects
older caches without those options. The device kernel hook also merges
`configs/wifi/cfr-kernel.config` into the source-built kernel so its System.map
contains the relay symbols used during vendor-module validation. This uses a
separate fragment because `KERNEL_CONFIG_OVERRIDE` writes multiple options on
one line. Rebuild and install the ROM/module to
use the source fixes; enabling CFR does not start a capture session by itself.

**Dialer.** `vendor_gms/0001` drops GoogleDialer from `gms_full.mk`. Evo's
GoogleDialer prebuilt carries `LOCAL_OVERRIDES_PACKAGES := Dialer`, which
deletes the AOSP Dialer that `telephony_product.mk` adds — the "crDroid phone
app" is that AOSP/Lineage Dialer. With GoogleDialer out of `PRODUCT_PACKAGES`
the override never fires (kati only applies it when the overriding module is
itself being built), so `packages/apps/Dialer` builds as the only dialer. The patch is that one line
out of `gms_full.mk`; nothing else in vendor/gms changes.

**Kernel Image.** Fetched from the latest `konoha-kernel-gki` release —
specifically the `KernelSU-Next` `root` asset that is *not* the
`bypasscharging` variant — and written to `vendor/extra/kernel/onyx/Image`,
verified to carry the arm64 `ARM\x64` magic. See
[`android_vendor_extra`](https://github.com/Loukious/android_vendor_extra) for
why only the Image is swapped and the kernel is still built from source.

There is no OTA-metadata overlay any more. crDroid had a build-time
`vendor/crDroidOTA/<device>.json` that `createjson.sh` read for the maintainer /
buildtype / donate fields; Evolution X has no equivalent, so
`overlay_ota_metadata()` and its preflight check were removed along with it.

## Evolution X migration state (2026-09-28)

The ROM base is now **Evolution X `cnb` / Android 17**. The main Onyx device,
hardware, kernel and vendor projects are synced to their `17.0` branches. The
MIUI camera helper/vendor projects remain on `16.0-onyx` because an Onyx
`17.0-onyx` branch is not published for them.

The device tree remains crDroid's
(`crdroidandroid/android_device_xiaomi_onyx` @ `17.0`) and continues to build
as `lineage_onyx` under Evolution X. The Android 17 sync and patch rebase were
completed before the current focused/product builds.

Several older Evolution/crDroid compatibility patches are no longer needed
because the Android 17 sources already contain the required behavior:

| Deleted | Why |
|---|---|
| `vendor_pixel_launcher/0001-gesture-hint-controller` | Evo ships the Pixel Launcher (`vendor_gms` → `NexusLauncherRelease.apk`) **and** an identically-named `PixelLauncherNoGestureHintOverlay` in `vendor/pixel-style`, and Evo's own `GestureNavigationSettingsFragment` already toggles it and restarts the launcher. The port and its privileged helper app were both redundant. |
| `packages_apps_Settings/0001-maintainer-from-prop` | Evo has no maintainer preference to patch. |
| `vendor_lineage/0003-unofficial-buildtype` | `EVO_BUILD_TYPE ?= Unofficial` is the default. |
| `vendor_lineage/0001-roomservice-allow-loukious` | Evo's `roomservice.py` is the older Lineage variant with no `validate_repository()` org allowlist, so there is nothing to allow. |

Rebased and round-trip verified against the synced Evolution X `cnb` tree:

| Patch | State |
|---|---|
| `packages_apps_Evolver/0001-gesture-navbar-space-ui` | new — replaces the crDroidSettings patch, which died with crDroid |
| `packages_apps_Settings/0001-gesture-navbar-space-ui` | rewritten. Evo's `SystemSettingListPreference` persists to `Settings.System` itself, so the 43 lines of Java the crDroid version carried are gone; the patch is now one XML block |
| `packages_apps_Updater/0001-self-hosted-ota-url` | re-aimed at Evo's `strings.xml` and at the current `evolution-cnb` branch of this repo |

The current layered tree has already been rebased and focused-build validated;
there is no remaining Android 16 patch-application step before the product build.

`device_xiaomi_onyx/0002-release-config-bp4a` is **not** droppable, contrary to
what this file said earlier. It is what turns the LHDC aconfig flags on for the
`bp4a` release — `lhdc_codec_support` and `a2dp_lhdc_api` to `ENABLED` /
`READ_ONLY` — via `configs/release/release_config_map.textproto` plus
`PRODUCT_RELEASE_CONFIG_MAPS +=` in `device.mk`. Dropping it would silently
disable the codec.

Two crDroid-side projects have to come along, because the device tree
references them unconditionally and both a bare `include` and a bare
`PRODUCT_PACKAGES` entry hard-fail when absent: `packages/apps/NotGameTurbo`
(`BoardConfig.mk:285`) and `packages/apps/LunarisDolby` (`device.mk:175`).

The old `drop-crdroid-bcr` patch is obsolete on the 17.0 device tree: current
Onyx sources no longer inherit `vendor/bcr/bcr.mk`, so there is nothing to
remove.

GApps come from Evolution X now — one variable,
`WITH_GMS := true` in `vendor/extra`, which makes
`vendor_evolution/config/common_full_phone.mk` inherit `vendor/gms/gms_full.mk`.
That replaces all five PixelOS manifest projects. Note `vendor_gms` uses Git LFS
against Evo's own server, so `repo init` needs `--git-lfs`.

## Deliberately excluded

Things present in my working tree that must **not** be patched in, or a clean
build breaks:

- `prebuilts/build-tools/path/*/{date,tar}` — six *deletions*, a local
  WSL-only workaround
- `device/xiaomi/onyx/__pycache__/`
- the whitespace-only reindent of
  `build/release/.../a2dp_lhdc_api_flag_values.textproto`
- the 350 MB of binaries in `vendor/xiaomi/onyx` (that's the overlay project's
  job, not a patch's)

There is no longer an `unapplied/` directory, and the Lockscreen Now Playing
port that used to live here was removed on 2026-08-28: it never produced a
confirmed detection on `onyx`, and Evolution X ships the feature natively, so
carrying a port is pointless. The removed work is preserved on the
`nowplaying-archive` branch of this repo (and of `android_vendor_extra`) if it
is ever needed again.

The continued Secure Auth work also adds framework
`0007-secure-auth-key-erasure` and `system_vold/0001-secure-auth-key-erasure`.
They provide native all-user key destruction with preserved IVold transaction
positions and an inert-backend host test module. The duress flow is wired to the
native erasure/shutdown path while normal credentials remain on Android's
LockSettings/Gatekeeper/Weaver/Synthetic Password/FBE stack.
The public switcher patch includes the internal unfiltered registry snapshot
used by erasure; public user lists remain filtered for Secure Spaces.

Framework `0008-secure-auth-duress-verifier` stores only dedicated stretched duress
verifiers. `0009-secure-space-entry-coordinator` adds both lockscreen clients,
identity-bound Scene proofs, cancellation, native lease revocation, and target-user
secondary admin policy resolution. The public privacy patch additionally filters
the power-menu count and public user identity; the Settings patch disables the
standard Users page inside a Secure Space. The latest lifecycle/privacy changes
passed the focused Android 17 integration build and the full Evolution X product
build. Post-flash runtime verification remains for upstream NFC without the retired workaround,
routed fingerprint-success haptic, and LHDC V5 vendor/offload behavior.

## October 19, 2026: reproducible security and device patch integration

The October 19 Evolution X Android 17 (`cnb`) OTA was compiled after a full
upstream sync and a manual reconciliation of Secure Spaces and duress changes.
The framework feature branches were **not** checked out as the ROM base:
`frameworks/base`, Settings, and `lineage-sdk` use the synced Evolution X
revisions, plus the numbered patches above. The biometric `MANAGE_USERS`
identity-resolution fix from `frameworks_base` commit `287bcdf` is included.

Before publication of these rebased patches, they were applied in filename
order to clean, unmodified files exported from the October 19 upstream Git
HEADs. All 15 security/Settings/lineage patches passed and all 169 resulting
source files were byte-for-byte identical to the locally built ROM tree.
The remaining device/kernel/Soong/codec patches were also clean-apply tested.
This is **patch application validation**, not a fresh complete ROM compilation
or on-device regression suite. Future upstream changes may require rebasing.

The Oct 19 source has the new WCN7750 CFR configuration and relay exports.
`kernel_xiaomi_sm8735/0004` reproduces the kernel source fragment that was
present in the successful local build; the device's CFR config extension is
retained from newer remote commits. `ci/refresh-radio-sha1s.py` now replaces
obsolete static SHA1s based on the actual staged firmware and must continue to
run **after** overlaying the hybrid G303/CN305 radio images.

Two obsolete patches are archived under `retired/` (NFC teardown and static
firmware SHA1). The generator no longer resurrects them.

## Manifest-synced Onyx 6.18 source builds

Use `local_manifests_onyx:evolution-cnb-konoha618` with this branch. The manifest
syncs `Loukious/onyx-android17-6.18:android17-6.18-lts` into
`kernel/platform/kernel-6.18`. `apply.sh` selects its `port/rom/BoardConfig.mk`
and skips the older 6.6 source patches, release Image download and WLAN overlay.
The legacy options and Image-only flow documented above apply to older branches.

The normal ROM build compiles the synced GKI, all matching native/platform modules
and corrected device trees through the source repository's verified Kleaf recipe.
Android generates its ramdisks, boot/DT images, DLKM partitions, AVB and OTA metadata.
Userspace headers are generated from the same GKI/module source; the adapter
retains three pinned legacy ION syscall headers needed by the vendor userspace.
Normal parallel module loading remains enabled.

```sh
ci/sync-local.py ~/Android/custom-rom --jobs 8
cd ~/Android/custom-rom
source build/envsetup.sh
breakfast onyx userdebug
m evolution -j8
```

The sync helper preserves local changes before fetching all manifest updates and
reapplying this patch set. KernelSU Next dev is resolved at build time. Kernel
objects are cached under `out/target/product/onyx/obj/KERNEL_BAZEL_OUT/kleaf-cache`
using Kleaf's supported incremental mode. The first build is cold; subsequent
builds reuse unchanged objects while repeating source, module and ABI checks.
The source-build receipt is `obj/KERNEL_OBJ/onyx-source-build.json` under the
product output directory. The obsolete prebuilt branch has been removed; the source branch is the active
ROM kernel input.
