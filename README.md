# crDroid 16 `onyx` patch set

Everything I carry on top of upstream crDroid for the POCO F7 (`onyx`),
kept as patches so the tree can be `repo sync`'d freely and re-patched
afterwards. Driven by `apply.sh`.

```sh
git clone -b crdroid-16.0 https://github.com/Loukious/crdroid_onyx_patches /tmp/patches
/tmp/patches/apply.sh /path/to/rom
```

`apply.sh` is **idempotent** — it reverse-checks each patch first and skips ones
already applied — and exits non-zero on a genuine failure so a build stops
rather than shipping a half-patched ROM.

| env | effect |
|---|---|
| `KERNEL_RELEASE_TAG` | konoha release to take the kernel Image from (default: latest) |
| `SKIP_KERNEL=1` | don't fetch/stage the kernel Image |
| `SKIP_FIRMWARE=1` | don't overlay the firmware blobs |
| `SKIP_OTA_METADATA=1` | don't overlay `vendor/crDroidOTA/<device>.json` |
| `GITHUB_TOKEN` | used for the release API if the kernel repo is private |

## The four features

**Gesture navigation space** — an extra settable inset below the gesture pill.
`frameworks/base` (`Settings.java`, `DisplayPolicy.java`) plus a small launcher
shim in `vendor/pixel/launcher` with its own privapp-permission allowlist entry
in `vendor/extra`.

**Google AI Wallpapers fix** — `PlayIntegritySpoofService` spoofs the integrity
verdict for the wallpaper generator, hooked from `ActivityThread`.

**LHDC A2DP codec** — the big one, spanning six projects:
`packages/modules/Bluetooth` (the codec itself, ~22.6k lines),
`vendor/qcom/opensource/interfaces` (the AIDL + frozen `aidl_api` snapshots),
`build/release` (the `lhdc_codec_support` aconfig value set),
`packages/modules/common` (`allowed_deps.txt` entries for the new NDK lib),
`frameworks/base` (`AudioSystem`, `BtHelper`), and `device/xiaomi/onyx`
(props + the `extract-files.py` blob fixups that byte-patch the two Qualcomm
offload libs).

**Pixel Lockscreen Now Playing** — ambient song recognition on the lockscreen
and AOD. Ported from Evolution-X
[`c83186b`](https://github.com/Evolution-X/frameworks_base/commit/c83186b883bd01a2c91b889184ebc9c8545ddc7d),
which reverse-engineered it out of CP2A `SystemUIGoogle`. 53 files, all in
`frameworks/base/packages/SystemUI`.

This is only the *display* half. The recognition itself is done by Device
Personalization Services (`com.google.android.as`), which broadcasts
`com.google.android.ambientindication.action.AMBIENT_INDICATION_{SHOW,HIDE,EXPAND}`;
`AmbientIndicationService` is the receiver. Both halves of what that needs are
already satisfied by the existing tree, so this patch is self-sufficient:

- DPS ships in the PixelOS GApps as
  `DevicePersonalizationPrebuiltPixel2024` (the Pixel 9 AiAi build).
- The gating system features are installed — `vendor/pixel/gms`'s
  `common-vendor.mk` copies `pixel_experience_2017.xml` … `_2024.xml`, and
  `nexus.xml` declares `com.google.android.feature.PIXEL_EXPERIENCE`.
- crDroid's `AndroidManifest.xml` already declared the
  `AMBIENT_INDICATION` permission; the patch relocates it and widens the
  protection level to `system|signature` so DPS in `/product/priv-app` can
  hold it.

Two integration points had to be re-done by hand rather than taken from the
upstream diff, and they are the parts to re-check whenever `frameworks/base`
moves under us:

- `SystemUICoreStartableModule.kt` — same binding, but crDroid's import block
  differs from Evolution-X's, so the upstream hunk's context does not match.
- `DefaultBlueprint.kt` — Evolution-X registers the compose lockscreen element
  through an `ElementProviderModule` dagger multibind that crDroid does not
  have. crDroid assembles providers by passing them to
  `LockscreenElementFactoryImpl.createRemembered(vararg)` instead, so
  `GoogleAmbientIndicationElementProvider` is added there. The
  `AmbientIndicationArea` element key and its slot in `LockscreenSceneLayout`
  already exist in crDroid, commented "vendor defined, not included in AOSP" —
  the port just fills them.

The legacy (non-compose) keyguard blueprint path needed no hand-holding:
crDroid already has the `@BindsOptionalOf @Named(KEYGUARD_AMBIENT_INDICATION_AREA_SECTION)`
hook, and the upstream `SystemUIModule.java` hunk that binds
`DefaultAmbientIndicationAreaSection` into it applies as-is.

## Layout

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
                                              0002-wallpaper-ai-spoof
                                              0003-lhdc-audio
                                              0004-pixel-lockscreen-now-playing
patches/packages_apps_Settings/               0001-maintainer-from-prop
patches/packages_apps_Updater/                0001-self-hosted-ota-url
patches/packages_modules_Bluetooth/           0001-lhdc-codec
patches/packages_modules_common/              0001-lhdc-allowed-deps
patches/vendor_lineage/                       0001-roomservice-allow-loukious
                                              0002-kernel-bin-override
                                              0003-unofficial-buildtype
patches/vendor_pixel_launcher/                0001-gesture-hint-controller
patches/vendor_qcom_opensource_interfaces/    0001-lhdc-aidl
patches/vendor_xiaomi_onyx/                   0001-firmware-sha1s-os3.0.302.0
```

## Unofficial build identity

`onyx` **has** official crDroid support, and three separate places in the tree
take that to mean any build for `onyx` is one. All three are corrected, because
otherwise this build credits someone else's work, solicits donations on their
behalf, and offers to overwrite itself with an official weekly.

**Version string** — `vendor_lineage/0003` sets `LINEAGE_BUILDTYPE :=
UNOFFICIAL` and appends it to both `LINEAGE_VERSION` and
`LINEAGE_DISPLAY_VERSION`, so the zip is
`crDroidAndroid-16.0-<date>-onyx-v12.11-UNOFFICIAL.zip` and Settings shows
`v12.11-<date>-UNOFFICIAL`. The suffix goes *last* deliberately:
`createjson.sh` reads the release version out of the zip name with
`cut -d'-' -f5`, which stays `v12.11`. The value is also kept outside the
`RELEASE NIGHTLY SNAPSHOT EXPERIMENTAL` set that `kernel.mk:231` hard-errors on
when a prebuilt kernel is forced — that guard is dormant here (this tree uses
`TARGET_OVERRIDE_KERNEL_BIN`, not `TARGET_FORCE_PREBUILT_KERNEL`) but there is
no reason to arm it.

**Maintainer and donate link** — `packages_apps_Settings/0001` teaches
`BuildMaintainerPreference` to honour `ro.crdroid.maintainer` and
`ro.crdroid.donate.url`, set in
[`vendor/extra/product.mk`](https://github.com/Loukious/android_vendor_extra) to
`Loukious` and `https://buymeacoffee.com/loukious`. A property, not a resource
overlay, because the stock code looks the maintainer up over the network from
crDroid's OTA index keyed on the device codename alone and *overrides* the
overlay string with whatever it finds — for `onyx` that is the official
maintainer and their PayPal. Setting the property short-circuits the fetch
entirely; leaving it unset restores the stock behaviour exactly.

**OTA source** — `packages_apps_Updater/0001` repoints `updater_server_url` at
[`ota/`](ota/) in this repo. See that directory's README for how to publish a
real update there; until then it is an empty `response` array, which the app
reports as "no updates".

**OTA metadata** — [`ota/crDroidOTA-onyx.json`](ota/crDroidOTA-onyx.json) is
copied by `apply.sh` over `vendor/crDroidOTA/onyx.json`, the file
`createjson.sh` reads at `bacon` time for the maintainer / buildtype / donate
fields of the OTA json it emits beside the zip. This one is an **overlay, not a
patch**, and that distinction is load-bearing: upstream regenerates that file on
every weekly release, so a context patch against it conflicts within days — it
took a build down on 2026-08-26 for exactly that reason. A whole-file copy
cannot conflict, and `createjson.sh`'s `extract_field()` is grep/sed based, so
it neither needs nor notices upstream's exact shape.

## What `apply.sh` does beyond patching

**Firmware overlay.** `vendor/xiaomi/onyx` syncs from crDroid's upstream GitLab
(4 GB, hosted free by them). Only the ~350 MB that differs — the OS3.0.302.0
`radio/` images and the two LHDC byte-patched blobs — lives in
[`proprietary_vendor_xiaomi_onyx-firmware`](https://github.com/Loukious/proprietary_vendor_xiaomi_onyx-firmware),
synced to `vendor/xiaomi/onyx-firmware` and copied over the top here. The two
images above GitHub's 100 MB blob limit are stored as `split` parts and
reassembled with a SHA-256 check.

Forking the 4 GB vendor repo was the obvious alternative and is a trap: its
history holds several revisions of the 137 MB `modem.img`, so a GitHub fork
blows the 1 GB free LFS tier and approaches the 2 GB per-push limit. The
overlay costs ~350 MB of ordinary git objects and no metered bandwidth.

**OTA metadata.** `ota/crDroidOTA-onyx.json` is copied over
`vendor/crDroidOTA/onyx.json` when the two differ. See "Unofficial build
identity" above for why this is a copy rather than a patch.

**Kernel Image.** Fetched from the latest `konoha-kernel-gki` release —
specifically the `KernelSU-Next` `root` asset that is *not* the
`bypasscharging` variant — and written to `vendor/extra/kernel/onyx/Image`,
verified to carry the arm64 `ARM\x64` magic. See
[`android_vendor_extra`](https://github.com/Loukious/android_vendor_extra) for
why only the Image is swapped and the kernel is still built from source.

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

See [`unapplied/`](unapplied/) for patches kept only for reference — notably
Evolution-X `1a9ae21`, the *non-Pixel* ambient Now Playing indicator, which is a
MediaSession re-skin rather than real recognition and needs nine prerequisite
commits crDroid does not have. `apply.sh` never looks outside `patches/*/`, so
nothing there can break a build.
