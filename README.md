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

## The three features

**Gesture navigation space** — an extra settable inset below the gesture pill.
`frameworks/base` (`Settings.java`, `DisplayPolicy.java`) plus a small launcher
shim in `vendor/pixel/launcher` with its own privapp-permission allowlist entry
in `vendor/extra`. The UI is split across two projects for a reason that is not
obvious: the `ListPreference` sits in `packages/apps/Settings`
(`res/xml/gesture_navigation_settings.xml`) but its strings and arrays sit in
`packages/apps/Evolver`. That resolves because Evolution X compiles Evolver
*into* the Settings APK — `Settings/Android.bp` lists `Evolver/res` in
`resource_dirs` and passes `--extra-packages org.evolution.settings` — so an
`@string` reference crosses the project boundary at build time. Put the strings
in Settings' own `res/values` instead and they are simply the wrong file to
edit; put the preference in an Evolver screen and it lands in the wrong menu.

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
patches/packages_apps_Evolver/                0001-gesture-navbar-space-ui
patches/packages_apps_Settings/               0001-maintainer-from-prop
                                              0002-gesture-navbar-space-ui
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

Every patch is a `git diff` of the working tree. `gen-patches.sh` also supports
diffing from a ref (`BASE`), because the gesture-navbar-space **UI** halves once
lived as local *commits* rather than as dirty files, which made a plain
`git diff` blind to them — every crave build before 2026-08-27 shipped the
framework half of the feature with no way to reach the setting. Nothing needs
`BASE` today; it is kept for the next time something gets committed locally.
**If you add a feature by committing it locally rather than leaving it
dirty, it will not be picked up unless you give its emit a `BASE`.**


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
`cut -d'-' -f5`, which stays `v12.11`. That patch is generated with `-U1`
(`CTX=1` in `gen-patches.sh`) rather than the usual three lines of context,
because at `-U3` the hunk carries `CR_VERSION := 12.11` as a context line and
upstream bumps that literal every release. The value is also kept outside the
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

## Evolution X migration state (2026-08-28)

The ROM base is moving from crDroid 16.0 to **Evolution X `bka`** — `bka`, not
the newer `cnb`: `bka` is Android 16 (`lineage-23.2`, `android-16.0.0_r4`) and
matches this device tree, its `bp4a` release config, the OS3.0.302.0 blobs and
the kernel. `cnb` is Android 17 and would be an OS jump on top of a ROM swap.

Rebased and round-trip verified against real Evolution X `bka` clones:

| Patch | State |
|---|---|
| `packages_apps_Evolver/0001-gesture-navbar-space-ui` | new — replaces the crDroidSettings patch, which died with crDroid |
| `packages_apps_Settings/0002-gesture-navbar-space-ui` | rewritten. Evo's `SystemSettingListPreference` persists to `Settings.System` itself, so the 43 lines of Java the crDroid version carried are gone; the patch is now one XML block |

Checked and still to do:

- `frameworks_base/0001-gesture-navbar-space` — Evo `bka` *does* declare
  `GESTURE_NAVBAR_LENGTH_MODE`, `GESTURE_NAVBAR_HEIGHT_MODE` and
  `GESTURE_NAVBAR_AUTO_HIDE`, and declares nothing named `GESTURE_NAVBAR_SPACE`,
  so the feature is genuinely ours and the `Settings.java` half should land
  cleanly. `DisplayPolicy.java` is 7 hunks deep and needs the synced tree to
  rebase honestly.
- The unofficial-identity trio (`packages_apps_Settings/0001-maintainer-from-prop`,
  `packages_apps_Updater/0001-self-hosted-ota-url`,
  `vendor_lineage/0003-unofficial-buildtype`) targets crDroid strings and paths.
  Evo has its own updater and its own buildtype plumbing; all three need
  re-aiming, not just re-applying.
- `vendor_lineage/0001` and `0002` still apply to the path `vendor/lineage`,
  which under Evo is the `vendor_evolution` repo mounted there — same path,
  different contents.
- `device_xiaomi_onyx/0002-release-config-bp4a` is probably droppable: `bp4a` is
  a standard AOSP release config and `vendor_evolution` ships no `build/release`
  overrides of its own.

Evo supplies GApps, so the PixelOS GMS manifest entries go away. Evo does **not**
ship Pixel Launcher, so `vendor/pixel/launcher` and its patch stay.

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
confirmed detection on `onyx`, and Evolution X ships the feature natively on
its `bka` branch, so carrying a port is pointless. The removed work is preserved
on the `nowplaying-archive` branch of this repo (and of `android_vendor_extra`)
if it is ever needed again.
