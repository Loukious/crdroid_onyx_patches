# crDroid 16 `onyx` patch set

Everything I carry on top of upstream crDroid for the Xiaomi Pad 7 (`onyx`),
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
| `GITHUB_TOKEN` | used for the release API if the kernel repo is private |

## The three features

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
patches/packages_modules_Bluetooth/           0001-lhdc-codec
patches/packages_modules_common/              0001-lhdc-allowed-deps
patches/vendor_lineage/                       0001-roomservice-allow-loukious
                                              0002-kernel-bin-override
patches/vendor_pixel_launcher/                0001-gesture-hint-controller
patches/vendor_qcom_opensource_interfaces/    0001-lhdc-aidl
patches/vendor_xiaomi_onyx/                   0001-firmware-sha1s-os3.0.302.0
```

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
