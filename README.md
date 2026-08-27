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

**Lockscreen Now Playing** — a Now Playing indicator on the lockscreen and
AOD. Two Evolution-X stacks in one patch, because on this device only one of
them can work:

- **`c83186b`** is the Pixel-native stack
  (`com.google.android.systemui.ambientmusic`), reverse-engineered out of CP2A
  `SystemUIGoogle`. It is purely a display layer — recognition is done by Device
  Personalization Services (`com.google.android.as`), which broadcasts
  `com.google.android.ambientindication.action.AMBIENT_INDICATION_{SHOW,HIDE,EXPAND}`.
- **The 14-commit chain ending `5748e136d`** (`1a9ae21` is the same change on
  another branch) is Evolution-X's own non-Pixel fork
  (`com.android.systemui.nowplaying.ambient`). It does **no audio recognition at
  all**: it is driven entirely by `MediaSessionManager`, so it works on any
  device.

`PixelAmbientIndicationDetector` chooses between them at runtime, and it only
picks the Pixel stack when `Build.BRAND == "google" && Build.MANUFACTURER ==
"google"` *and* `com.google.android.as` is enabled. `onyx` is `POCO`/`Xiaomi`, so
**the fork is what runs here and the Pixel stack stays dormant.** Both ship
because that is how Evolution-X ships them, and because the fork's
Pixel-hardware fallback path *is* the Pixel stack.

**The Pixel stack's blocker is the DSP, and the DSP is avoidable.** A 45 s
PAL/AGM/ACDB trace taken while ASI armed the SoundTrigger session shows the ADSP
rejecting Google's model outright — `CustomVAInterface: SetParameter: Unsupported
param id 2`, `graph_set_config failed -131`, `AcdbCmdGetGraphAlias Error[19]:
Unable to find graph key vector`. `module_type="CUSTOM1"` resolves to model type
102 -> `CustomVAInterface`, and `libcustomva_intf.so` here is a Qualcomm stub
with no ACDB graph behind it. PAL still reports success upward, so the session
ends up armed and inert and `recognition_history` stays empty no matter which
model is shipped. **Do not try to fix that by regenerating the model** — nothing
on the DSP side can work without an ACDB graph we do not have.

But recognition never ran on the DSP. ASI carries its own userspace recognizer
(`libsense.so`, `libsense_nnfp_v3.so`) and the shipped model is TFLite; the DSP
was only the low-power microphone. Which source ASI opens is one DeviceConfig
flag, `NowPlaying__ambient_music_use_dsp_audio_source`, which defaults to **true**
and therefore silently strands every non-Pixel. Set false, ASI opens a plain
16 kHz mono mic `AudioRecord` that touches neither SoundTrigger nor the DSP
wrapper class. It is set in
`vendor/extra/rro/SimpleDeviceConfigOverlayOnyx/res/values/config.xml`.

**That is necessary but not sufficient, and the RRO comment says so.** There are
two DSP dependencies, not one. The second is the *trigger*: `Lyyx`, the object
every stage of the ambient pipeline consumes, has exactly one constructor call
site in the APK, inside a factory taking a
`SoundTrigger$RecognitionEvent` — a class ASI never constructs itself. Its only
callers are a `SoundTriggerDetectionService` subclass and a `BroadcastReceiver`.
So the pipeline waits on the framework to deliver a real recognition event, which
`onyx` never does. The flag decides where audio comes from *after* that event; it
starts nothing. Closing that gap means synthesizing the event from
`frameworks/base` — a project, not a config change, and not attempted here.

Separately, **on-demand recognition should already work**: `Lyxx;->d()` opens its
own mic `AudioRecord` and drives `android.media.musicrecognition.RecognitionRequest`
(`MusicRecognitionManager`) with no SoundTrigger in the path. That is the "identify
this song" button rather than passive detection.

All three findings, with the decompiled evidence, are recorded in the RRO comment
block and in `vendor/extra/product.mk` above the four `music_detector` blobs.

Note this is all orthogonal to the lockscreen indicator below: the Evolution-X
fork shows music playing *on* the device with no recognition at all, while ASI is
what would identify music playing *in the room*.

74 files, all but one in `frameworks/base/packages/SystemUI`; the exception is
the 12 `Settings.System.NOWPLAYING_*` constants in
`core/java/android/provider/Settings.java`. The path list is checked into
[`nowplaying-paths.txt`](nowplaying-paths.txt) and `gen-patches.sh` asserts its
length, so a path silently dropping out of the patch fails loudly.

The two stacks are **not** split into separate patches, deliberately. They share
eight files (`SystemUIModule.java`, `SysUIComponent.java`,
`ambientindication_strings.xml`, `ids.xml`, both keyguard blueprints,
`KeyguardSectionsModule.kt`, `AxDynamicBarKeyguardChipSection.kt`), and a patch
whose hunks are only *half* applied neither applies nor reverse-applies — which
`apply.sh` correctly treats as a hard error. One feature, one patch.

Things to re-check whenever `frameworks/base` moves under us:

- `SystemUICoreStartableModule.kt` — same binding as upstream, but crDroid's
  import block differs, so the upstream hunk's context does not match.
- `DefaultBlueprint.kt` — Evolution-X registers the compose lockscreen element
  through an `ElementProviderModule` dagger multibind crDroid does not have.
  crDroid assembles providers by passing them to
  `LockscreenElementFactoryImpl.createRemembered(vararg)` instead, so
  `GoogleAmbientIndicationElementProvider` is added there. The
  `AmbientIndicationArea` element key and its slot in `LockscreenSceneLayout`
  already exist in crDroid, commented "vendor defined, not included in AOSP" —
  the port just fills them.
- `CentralSurfacesImpl.java` is **net-zero** across the 14-commit chain:
  `0f9d699c2` wires `NowPlayingViewController` into `attachCustomOverlays()` and
  `5748e136d` removes every line of it. It needs no edit, and `0f9d699c2`'s
  `attachCustomOverlays()` refactor must not be applied.
- Lyrics are scoped to `LyricsFetcher.java` alone (a standalone lrclib.net
  singleton). `LyricViewController.kt` / `LyricControllerModern.kt` belong to a
  separate Evolution-X status-bar-lyrics feature and are left out; pulling them
  in would need `Settings.Secure.STATUS_BAR_SHOW_LYRIC`, which crDroid lacks.
- crDroid has no `KEYGUARD_BATTERY_CHARGING_SECTION` and no
  `evolution_dimens.xml` (the four dimens went into `cr_dimens.xml`), and has an
  extra `KeyguardClockStyleSectionModule` in `KeyguardSectionsModule.kt`.

The legacy (non-compose) keyguard blueprint path needed no hand-holding:
crDroid already has the `@BindsOptionalOf @Named(KEYGUARD_AMBIENT_INDICATION_AREA_SECTION)`
hook, and the upstream `SystemUIModule.java` hunk that binds
`DefaultAmbientIndicationAreaSection` into it applies as-is.

The settings UI is a separate patch against `packages/apps/crDroidSettings`,
ported from the Evolver commits `f7631bb` + `a7d572e` + `860ff88`.
crDroidSettings has **no build file of its own** —
`packages/apps/Settings/Android.bp` globs `crDroidSettings/{src,res}` — so it
lands in the Settings APK, and Kotlin `@SearchIndexable` works there.
`org.evolution.settings.preferences.*` maps 1:1 onto
`com.crdroid.settings.preferences.*`, and `MetricsProto.MetricsEvent.EVOLVER`
becomes `CRDROID_SETTINGS`. A `reset()` was added (Evolver has none) and hooked
into `LockScreen.java`'s reset menu beside `MediaArtSettings.reset`.

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
                                              0004-lockscreen-now-playing
patches/packages_apps_Settings/               0001-maintainer-from-prop
                                              0002-gesture-navbar-space-ui
patches/packages_apps_crDroidSettings/        0001-gesture-navbar-space-ui
                                              0002-lockscreen-now-playing-settings
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

Most patches are a `git diff` of the working tree. Two are not: the
gesture-navbar-space **UI** halves live as local *commits* on
`loukious/feature/gesture-navbar-space` in the `Settings` and `crDroidSettings`
forks, so a plain `git diff` never saw them and they were missing from the patch
set entirely until 2026-08-27 — every crave build before that shipped the
framework half of the feature with no way to reach the setting. `gen-patches.sh`
now diffs those two from `$UPSTREAM_REF` (`m/16.0`) instead of from the index.
`crDroidSettings/res/values/cr_strings.xml` is edited by both that commit and the
uncommitted Now Playing UI, so `0001` stops its diff at `HEAD` (`HEADEND=1`) and
`0002` starts there: disjoint endpoints, so neither patch carries the other's
hunks. **If you add a feature by committing it locally rather than leaving it
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

There is no longer an `unapplied/` directory. It held Evolution-X `1a9ae21` with
a note saying the non-Pixel Now Playing indicator was neither used nor needed;
that conclusion was wrong — the Pixel stack's display layer sits idle here
because `PixelAmbientIndicationDetector` correctly reports a non-Pixel (see
"Lockscreen Now Playing" above), so the whole 14-commit chain was
ported and now ships in `0004-lockscreen-now-playing.patch`. The parked
single-commit copy was a subset of what is applied and only invited someone to
re-apply it, so it is gone.
