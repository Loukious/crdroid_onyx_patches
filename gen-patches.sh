#!/usr/bin/env bash
#
# Generate the crDroid onyx patch set from the working tree at $ROM.
#
# Splits the local modifications into per-project, per-feature patches.
# Untracked files are recorded with `git add -N` first so that the resulting
# patch *creates* them; the index is reset afterwards, so the working tree and
# the user's staging area are left exactly as they were found.
#
set -euo pipefail

ROM="${ROM:-/home/loukious/android/crdroid}"
OUT="${OUT:-/home/loukious/android/rom-automation/crdroid_onyx_patches}"

die() { echo "FATAL: $*" >&2; exit 1; }

CTX=""       # per-patch diff context override, see emit()
FILTER=()    # per-patch hunk-filter.py args, see emit()
APPEND=0     # when 1, emit() appends instead of truncating
BASE=""      # when set, emit() diffs from this ref instead of the index
HEADEND=0    # with BASE set, diff BASE..HEAD instead of BASE..worktree
UPSTREAM_REF="${UPSTREAM_REF:-m/16.0}"   # repo's manifest-revision ref
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[ -d "$ROM/.repo" ] || die "no .repo in $ROM"

rm -rf "$OUT/patches"
mkdir -p "$OUT/patches"

# Untracked paths that must never enter a patch.
#   __pycache__        - build litter
EXCLUDE_RE='__pycache__'

# stage_intent <project> -- record intent-to-add for untracked, filtered files
stage_intent() {
    local proj="$1"
    local files
    files=$(git -C "$ROM/$proj" ls-files -o --exclude-standard | grep -Ev "$EXCLUDE_RE" || true)
    if [ -n "$files" ]; then
        # shellcheck disable=SC2086
        printf '%s\n' "$files" | tr '\n' '\0' | xargs -0 --no-run-if-empty \
            git -C "$ROM/$proj" add -N --
    fi
}

# emit <project> <patchname> <pathspec...>
emit() {
    local proj="$1" name="$2"; shift 2
    local dir="$OUT/patches/${proj//\//_}"
    mkdir -p "$dir"
    local target="$dir/$name"
    # CTX overrides the diff context width. Fewer context lines make a patch
    # survive unrelated churn near the hunk -- see the version.mk emit below.
    # FILTER selects individual hunks (hunk-filter.py) so that one file edited by
    # two unrelated features can be split between their patches -- see the
    # Settings.java emits below.
    # APPEND=1 concatenates onto an existing patch, which is how a patch made of
    # two differently-filtered diffs of the same project is assembled. `git apply`
    # is happy with multiple file sections in one file.
    [ "$APPEND" = 1 ] || : > "$target"
    # BASE makes emit() diff from a ref rather than from the index, which is the
    # only way to capture work that was *committed* locally. HEADEND=1 stops the
    # diff at HEAD so a committed feature and an uncommitted one can share a file
    # without either patch carrying the other's hunks -- see crDroidSettings'
    # cr_strings.xml, which both the gesture-navbar and Now Playing UIs edit.
    local range=()
    if [ -n "$BASE" ]; then
        git -C "$ROM/$proj" rev-parse --verify -q "$BASE" >/dev/null \
            || die "$proj: base ref '$BASE' does not resolve"
        range=("$BASE")
        [ "$HEADEND" = 1 ] && range+=(HEAD)
    fi
    # shellcheck disable=SC2086  # deliberately unquoted: empty CTX must vanish
    if [ "${#FILTER[@]}" -gt 0 ]; then
        git -C "$ROM/$proj" diff --no-color --no-renames --binary \
            ${CTX:+-U$CTX} ${range[@]+"${range[@]}"} -- "$@" \
            | python3 "$HERE/hunk-filter.py" "${FILTER[@]}" >> "$target"
    else
        git -C "$ROM/$proj" diff --no-color --no-renames --binary \
            ${CTX:+-U$CTX} ${range[@]+"${range[@]}"} -- "$@" >> "$target"
    fi
    if [ ! -s "$target" ]; then
        rm -f "$target"
        die "$proj: patch $name came out EMPTY (pathspec: $*)"
    fi
    printf '  %-42s %6d lines\n' "${proj//\//_}/$name" "$(wc -l < "$target")"
}

PROJECTS="build/release device/xiaomi/onyx frameworks/base
packages/apps/Settings packages/apps/Updater packages/apps/crDroidSettings
packages/modules/Bluetooth packages/modules/common
vendor/lineage vendor/pixel/launcher vendor/qcom/opensource/interfaces
vendor/xiaomi/onyx"

cleanup() {
    for p in $PROJECTS; do
        git -C "$ROM/$p" reset -q || true
    done
}
trap cleanup EXIT

for p in $PROJECTS; do
    stage_intent "$p"
done

echo "Generating patches into $OUT/patches"

# ---------------------------------------------------------------- frameworks/base
# Settings.java is edited by two features: GESTURE_NAVBAR_SPACE_MODE here and the
# 12 NOWPLAYING_* constants in the Now Playing patch below. Drop the latter's
# hunk rather than let both patches carry the whole file -- a patch that is only
# half-applied neither applies nor reverse-applies, which apply.sh treats (right)
# as a hard error.
FILTER=(--drop 'NOWPLAYING_[A-Z]')
emit frameworks/base 0001-gesture-navbar-space.patch \
    core/java/android/provider/Settings.java \
    services/core/java/com/android/server/wm/DisplayPolicy.java
FILTER=()

emit frameworks/base 0002-wallpaper-ai-spoof.patch \
    core/java/android/app/ActivityThread.java \
    core/java/android/security/pif/PlayIntegritySpoofService.java

emit frameworks/base 0003-lhdc-audio.patch \
    media/java/android/media/AudioSystem.java \
    services/core/java/com/android/server/audio/BtHelper.java

# Lockscreen Now Playing. Two halves that ship together, exactly as Evolution X
# ships them:
#
#   * the Pixel-native stack (com.google.android.systemui.ambientmusic), ported
#     from Evolution-X c83186b. It waits for AMBIENT_INDICATION broadcasts from
#     com.google.android.as, which never arrive on onyx -- the Qualcomm ADSP here
#     has no DSP graph for Google's music_detector model (see vendor/extra/
#     product.mk for the PAL/AGM/ACDB proof). Kept because it is the fallback on
#     real Pixels and because the non-Pixel fork below reuses its resources.
#
#   * the non-Pixel fork (com.android.systemui.nowplaying.ambient), the 14-commit
#     chain on Evolution-X cnb ending at 5748e136d. This one does NO audio
#     recognition: it is driven entirely by MediaSessionManager, which is why it
#     works on any device. This is the half that actually lights up the indicator
#     on onyx. PixelAmbientIndicationDetector picks between the two at runtime.
#
# 74 files, all under packages/SystemUI, enumerated in a list rather than globbed:
# SystemUI is full of unrelated local churn, and `packages/SystemUI` as a pathspec
# would hoover it up. The list is authoritative -- regenerate it with
#   sed -n 's|^diff --git a/\(.*\) b/.*|\1|p' <the patch> | sort -u
# if the port grows a file.
#
# Settings.java is emitted first, filtered to the NOWPLAYING_* hunk only; see the
# 0001 emit above for why.
NOWPLAYING_PATHS="${NOWPLAYING_PATHS:-$HERE/nowplaying-paths.txt}"
[ -f "$NOWPLAYING_PATHS" ] || die "missing path list $NOWPLAYING_PATHS"
mapfile -t NP_PATHS < "$NOWPLAYING_PATHS"
[ "${#NP_PATHS[@]}" -eq 74 ] || die "expected 74 Now Playing paths, got ${#NP_PATHS[@]}"
FILTER=(--keep 'NOWPLAYING_[A-Z]')
emit frameworks/base 0004-lockscreen-now-playing.patch \
    core/java/android/provider/Settings.java
FILTER=()
APPEND=1
emit frameworks/base 0004-lockscreen-now-playing.patch "${NP_PATHS[@]}"
APPEND=0

# ------------------------------------------------------------------------- LHDC
emit packages/modules/Bluetooth 0001-lhdc-codec.patch .

emit vendor/qcom/opensource/interfaces 0001-lhdc-aidl.patch .

# Only the new flag file. The modified a2dp_lhdc_api_flag_values.textproto is a
# whitespace-only reindent (verified with `git diff -w`) and is dropped.
emit build/release 0001-lhdc-aconfig-flag.patch \
    aconfig/bp4a/com.android.bluetooth.flags/lhdc_codec_support_flag_values.textproto

emit packages/modules/common 0001-lhdc-allowed-deps.patch build/allowed_deps.txt

# --------------------------------------------------------------- device/xiaomi/onyx
emit device/xiaomi/onyx 0001-vendor-extra-kernel-hook.patch BoardConfig.mk

emit device/xiaomi/onyx 0002-release-config-bp4a.patch device.mk configs/release

emit device/xiaomi/onyx 0003-lhdc-aptx-props-and-blob-fixups.patch \
    properties/product.prop extract-files.py

emit device/xiaomi/onyx 0004-firmware-os3.0.302.0.patch proprietary-firmware.txt

# ------------------------------------------------------------ vendor/pixel/launcher
emit vendor/pixel/launcher 0001-gesture-hint-controller.patch \
    products/launcher.mk apps overlays

# ------------------------------------------------------------------- vendor/lineage
emit vendor/lineage 0001-roomservice-allow-loukious.patch build/tools/roomservice.py

emit vendor/lineage 0002-kernel-bin-override.patch build/tasks/kernel.mk

# -U1, deliberately. With the default 3 lines of context this hunk carries
# `CR_VERSION := 12.11` as a context line, and upstream bumps that literal every
# crDroid release -- which would rot the patch the same way the vendor/crDroidOTA
# one did, and `--depth 1` leaves --3way no blob to recover with. The changed
# lines cannot be moved away from it (they sit two lines below), so drop the
# context instead: `# Internal version` and `LINEAGE_VERSION :=` are distinctive
# enough on their own.
CTX=1
emit vendor/lineage 0003-unofficial-buildtype.patch config/version.mk
CTX=""

# --------------------------------------------------- unofficial build identity
# onyx has official crDroid support, and three separate places assume that means
# an official build. Two are corrected by a patch in their own project; the third,
# vendor/crDroidOTA/onyx.json, is *not* patched -- upstream regenerates that file
# every weekly release, so a patch there conflicts within days. apply.sh copies
# ota/crDroidOTA-onyx.json over it instead.
emit packages/apps/Settings 0001-maintainer-from-prop.patch \
    src/com/android/settings/deviceinfo/firmwareversion/BuildMaintainerPreference.kt

# The UI half of gesture-navbar-space. This lives as a *local commit* on
# loukious/feature/gesture-navbar-space rather than as a working-tree change, so
# a plain `git diff` never saw it and it was silently missing from the patch set
# -- which meant every crave build shipped the framework half with no way to
# reach the setting. BASE captures it. Do not "simplify" this back to a
# working-tree diff.
BASE="$UPSTREAM_REF"
emit packages/apps/Settings 0002-gesture-navbar-space-ui.patch \
    res/xml/gesture_navigation_settings.xml \
    src/com/android/settings/gestures/GestureNavigationSettingsFragment.java
BASE=""

emit packages/apps/Updater 0001-self-hosted-ota-url.patch \
    app/src/main/res/values/strings.xml

# ----------------------------------------------------------- crDroidSettings
# Two features, and they share res/values/cr_strings.xml.
#
# 0001 (gesture navbar) is a local COMMIT; 0002 (Now Playing) is a working-tree
# change on top of it. So 0001 diffs UPSTREAM_REF..HEAD and 0002 diffs
# HEAD..worktree: disjoint endpoints, so neither patch carries the other's hunks
# and the pair applies in glob order onto a clean sync. Their cr_strings.xml
# hunks are ~350 lines apart, so their context does not overlap either.
BASE="$UPSTREAM_REF"; HEADEND=1
emit packages/apps/crDroidSettings 0001-gesture-navbar-space-ui.patch \
    res/values/cr_strings.xml \
    src/com/crdroid/settings/fragments/Navigation.java
BASE=""; HEADEND=0

# The settings companion to frameworks_base 0004, ported from
# Evolution-X/packages_apps_Evolver f7631bb + a7d572e + 860ff88. crDroidSettings
# has no build file of its own -- packages/apps/Settings/Android.bp globs
# crDroidSettings/{src,res} -- so these land in the Settings APK.
emit packages/apps/crDroidSettings 0002-lockscreen-now-playing-settings.patch \
    res/values/cr_arrays.xml \
    res/values/cr_strings.xml \
    res/xml/crdroid_settings_lockscreen.xml \
    res/xml/nowplaying_settings.xml \
    src/com/crdroid/settings/fragments/LockScreen.java \
    src/com/crdroid/settings/fragments/lockscreen/NowPlayingSettings.kt \
    src/com/crdroid/settings/utils/PixelAmbientIndicationDetector.kt

# --------------------------------------------------------------- vendor/xiaomi/onyx
# Only Android.mk. The 351MB of rebuilt radio/ images and the 2 byte-patched
# LHDC blobs ship as a separate overlay project (onyx-firmware) that apply.sh
# copies in -- they are binaries and have no business in a patch. Android.mk is
# text, so it stays a patch: if crDroid regenerates it upstream this conflicts
# loudly instead of being silently clobbered.
emit vendor/xiaomi/onyx 0001-firmware-sha1s-os3.0.302.0.patch Android.mk

# Now Playing, HAL half. ASI loads /system/etc/firmware/music_detector.sound_model
# as a generic SoundTrigger model with vendorUuid 9f6ad62a-1f0b-11e7-87c5-40a8f03d3f15.
# Qualcomm PAL treats vendor_uuid as a strict WHITELIST: a model matching no
# <stream_config> is rejected at loadModel with INTERNAL_ERROR (code 5), and ASI's
# ModelReloadService then retries forever -- which is what pinned Now Playing on
# "Downloading song database". Xiaomi shipped 13 stream_configs and none for this
# uuid (HyperOS has no Now Playing), so we add a 14th via CUSTOM_VOICE_UI, PAL's
# documented third-party hook (libcustomva_intf.so / module_type CUSTOM1 -- Xiaomi
# already uses it 6x for XiaoAi). Capture profiles are lifted from HOTWORD_VOICE_UI,
# proven working on this device, NOT the CUSTOM_NS/CUSTOM_ECNS variants.
# Note onyx has NO sound_trigger_platform_info.xml -- Xiaomi folded the soundtrigger
# platform info into the PAL resource-manager XML. Find it by content, not filename.
# The userspace half of Now Playing lives in vendor/extra (SimpleDeviceConfig RRO).
emit vendor/xiaomi/onyx 0002-soundtrigger-google-music-detector.patch \
    proprietary/odm/etc/audio/sku_tuna/resourcemanager_tuna_mtp.xml

echo
echo "Done. Totals:"
find "$OUT/patches" -name '*.patch' | wc -l | xargs echo "  patch files:"
du -sh "$OUT/patches" | awk '{print "  size:        "$1}'
