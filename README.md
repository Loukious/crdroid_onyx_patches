# Evolution X 17 `onyx` patch set

Everything I carry on top of upstream Evolution X for the POCO F7 (`onyx`),
kept as patches so the tree can be `repo sync`'d freely and re-patched
afterwards. Driven by `apply.sh`.

```sh
git clone -b evolution-cnb https://github.com/Loukious/crdroid_onyx_patches /tmp/patches
/tmp/patches/apply.sh /path/to/rom
```

The repo name still says `crdroid` because renaming it would break every URL
that references it; the contents target Evolution X `cnb` / Android 17. The
crDroid-era set is preserved on the `crdroid-16.0` branch.

`apply.sh` is **idempotent** — it reverse-checks each patch first and skips ones
already applied — and exits non-zero on a genuine failure so a build stops
rather than shipping a half-patched ROM.

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
NXP NFC teardown-race fix is preserved separately under
`patches/hardware_nxp_nfc`. Post-flash runtime validation is still required for
the patched NFC HAL and the routed fingerprint haptic. See
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
patches/build_release/                        0001-lhdc-aconfig-flag
patches/device_xiaomi_onyx/                   0001-vendor-extra-kernel-hook
                                              0002-release-config-bp4a
                                              0003-lhdc-aptx-props-and-blob-fixups
                                              0004-firmware-os3.0.302.0
patches/frameworks_base/                      0001-gesture-navbar-space
                                              0003-secure-spaces-full-user-type
                                              0004-authentication-user-identity
                                              0005-secure-space-credential-router
                                              0006-secure-space-public-switcher-privacy
                                              0007-secure-auth-key-erasure
                                              0008-secure-auth-duress-verifier
                                              0009-secure-space-entry-coordinator
                                              0010-secure-space-fingerprint-routing
patches/hardware_nxp_nfc/                     0001-fix-client-thread-teardown-race
patches/lineage-sdk/                          0001-secure-space-user-switch-observer-acks
patches/packages_apps_Evolver/                0001-gesture-navbar-space-ui
patches/packages_apps_Settings/               0001-gesture-navbar-space-ui
                                              0002-secure-spaces-management
patches/packages_apps_Updater/                0001-self-hosted-ota-url
patches/packages_modules_Bluetooth/           0001-lhdc-v5-qti-offload
patches/system_security/                      0001-secure-auth-biometric-user-scope
patches/system_vold/                          0001-secure-auth-key-erasure
patches/vendor_gms/                           0001-keep-aosp-dialer
patches/vendor_lineage/                       0001-kernel-bin-override
patches/vendor_qcom_opensource_interfaces/    0001-lhdc-aidl
patches/vendor_xiaomi_onyx/                   0001-firmware-sha1s-os3.0.302.0
```

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
(4 GB, hosted free by them). Only the ~350 MB that differs — the OS3.0.302.0
`radio/` images and the two LHDC byte-patched blobs — lives in
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
older caches without those options. Rebuild and install the ROM/module to
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
build. Post-flash runtime verification remains for the new NFC teardown path,
routed fingerprint-success haptic, and LHDC V5 vendor/offload behavior.
