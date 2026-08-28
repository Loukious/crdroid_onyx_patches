# Evolution X 16 `onyx` patch set

Everything I carry on top of upstream Evolution X for the POCO F7 (`onyx`),
kept as patches so the tree can be `repo sync`'d freely and re-patched
afterwards. Driven by `apply.sh`.

```sh
git clone -b evolution-bka https://github.com/Loukious/crdroid_onyx_patches /tmp/patches
/tmp/patches/apply.sh /path/to/rom
```

The repo name still says `crdroid` because renaming it would break every URL
that references it; the contents target Evolution X `bka`. The crDroid-era set
is preserved on the `crdroid-16.0` branch.

`apply.sh` is **idempotent** — it reverse-checks each patch first and skips ones
already applied — and exits non-zero on a genuine failure so a build stops
rather than shipping a half-patched ROM.

| env | effect |
|---|---|
| `KERNEL_RELEASE_TAG` | konoha release to take the kernel Image from (default: latest) |
| `SKIP_KERNEL=1` | don't fetch/stage the kernel Image |
| `SKIP_FIRMWARE=1` | don't overlay the firmware blobs |
| `GITHUB_TOKEN` | used for the release API if the kernel repo is private |

## The three features

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
patches/packages_apps_Settings/               0001-gesture-navbar-space-ui
patches/packages_apps_Updater/                0001-self-hosted-ota-url
patches/packages_modules_Bluetooth/           0001-lhdc-codec
patches/packages_modules_common/              0001-lhdc-allowed-deps
patches/vendor_lineage/                       0001-kernel-bin-override
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

## Build identity

Nothing to patch. `vendor_evolution/config/version.mk` has
`EVO_BUILD_TYPE ?= Unofficial`, so an unofficial build is what you get by
default, and the zip comes out
`EvolutionX-16.0-<date>-onyx-11.10-Unofficial.zip`.

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
[`proprietary_vendor_xiaomi_onyx-firmware`](https://github.com/Loukious/proprietary_vendor_xiaomi_onyx-firmware),
synced to `vendor/xiaomi/onyx-firmware` and copied over the top here. The two
images above GitHub's 100 MB blob limit are stored as `split` parts and
reassembled with a SHA-256 check.

Forking the 4 GB vendor repo was the obvious alternative and is a trap: its
history holds several revisions of the 137 MB `modem.img`, so a GitHub fork
blows the 1 GB free LFS tier and approaches the 2 GB per-push limit. The
overlay costs ~350 MB of ordinary git objects and no metered bandwidth.

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

## Evolution X migration state (2026-08-28)

The ROM base moved from crDroid 16.0 to **Evolution X `bka`** — `bka`, not the
newer `cnb`: `bka` is Android 16 (`lineage-23.2`, `android-16.0.0_r4`) and
matches this device tree, its `bp4a` release config, the OS3.0.302.0 blobs and
the kernel. `cnb` is Android 17 and would be an OS jump on top of a ROM swap.

The device tree is still crDroid's (`crdroidandroid/android_device_xiaomi_onyx`
@ `16.0`) and drops in unrenamed: `PRODUCT_NAME := lineage_onyx`,
`lineage_onyx.mk` inherits `vendor/lineage/config/common_full_phone.mk` which
`vendor_evolution` ships, and `breakfast onyx` resolves to
`lineage_onyx-bp4a-userdebug` — byte-identical to what it was under crDroid.

**Patch count went 20 → 16.** Four were deleted outright, because Evolution X
already does the thing:

| Deleted | Why |
|---|---|
| `vendor_pixel_launcher/0001-gesture-hint-controller` | Evo ships the Pixel Launcher (`vendor_gms` → `NexusLauncherRelease.apk`) **and** an identically-named `PixelLauncherNoGestureHintOverlay` in `vendor/pixel-style`, and Evo's own `GestureNavigationSettingsFragment` already toggles it and restarts the launcher. The port and its privileged helper app were both redundant. |
| `packages_apps_Settings/0001-maintainer-from-prop` | Evo has no maintainer preference to patch. |
| `vendor_lineage/0003-unofficial-buildtype` | `EVO_BUILD_TYPE ?= Unofficial` is the default. |
| `vendor_lineage/0001-roomservice-allow-loukious` | Evo's `roomservice.py` is the older Lineage variant with no `validate_repository()` org allowlist, so there is nothing to allow. |

Rebased and round-trip verified against real Evolution X `bka` clones:

| Patch | State |
|---|---|
| `packages_apps_Evolver/0001-gesture-navbar-space-ui` | new — replaces the crDroidSettings patch, which died with crDroid |
| `packages_apps_Settings/0001-gesture-navbar-space-ui` | rewritten. Evo's `SystemSettingListPreference` persists to `Settings.System` itself, so the 43 lines of Java the crDroid version carried are gone; the patch is now one XML block |
| `packages_apps_Updater/0001-self-hosted-ota-url` | re-aimed at Evo's `strings.xml` and at the `evolution-bka` branch of this repo |

Still to rebase against the synced tree:

- `frameworks_base/0001-gesture-navbar-space` — Evo `bka` *does* declare
  `GESTURE_NAVBAR_LENGTH_MODE`, `GESTURE_NAVBAR_HEIGHT_MODE` and
  `GESTURE_NAVBAR_AUTO_HIDE`, and declares nothing named `GESTURE_NAVBAR_SPACE`,
  so the feature is genuinely ours and the `Settings.java` half should land
  cleanly. `DisplayPolicy.java` is 7 hunks deep and needs the synced tree to
  rebase honestly.
- `vendor_lineage/0001-kernel-bin-override` — same path, different repo:
  `vendor/lineage` is where `vendor_evolution` mounts. The anchor survives
  (`build/tasks/kernel.mk` is 839 lines; the `TARGET_NO_KERNEL_OVERRIDE` region
  runs 106–838 and `$(INSTALLED_KERNEL_TARGET): $(KERNEL_BIN)` is at 823, up
  from ~791 under crDroid), so the patch needs renumbered context, not a
  redesign.
- the four `device_xiaomi_onyx` patches.

`device_xiaomi_onyx/0002-release-config-bp4a` is **not** droppable, contrary to
what this file said earlier. It is what turns the LHDC aconfig flags on for the
`bp4a` release — `lhdc_codec_support` and `a2dp_lhdc_api` to `ENABLED` /
`READ_ONLY` — via `configs/release/release_config_map.textproto` plus
`PRODUCT_RELEASE_CONFIG_MAPS +=` in `device.mk`. Dropping it would silently
disable the codec.

Three crDroid-side projects have to come along, because the device tree
references them unconditionally and both a bare `include` and a bare
`PRODUCT_PACKAGES` entry hard-fail when absent: `packages/apps/NotGameTurbo`
(`BoardConfig.mk:285`), `vendor/bcr` (`device.mk:31`) and
`packages/apps/LunarisDolby` (`device.mk:175`).

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
