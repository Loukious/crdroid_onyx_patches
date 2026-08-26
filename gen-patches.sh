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

CTX=""   # per-patch diff context override, see emit()

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
    # shellcheck disable=SC2086  # deliberately unquoted: empty CTX must vanish
    git -C "$ROM/$proj" diff --no-color --no-renames --binary \
        ${CTX:+-U$CTX} -- "$@" > "$target"
    if [ ! -s "$target" ]; then
        rm -f "$target"
        die "$proj: patch $name came out EMPTY (pathspec: $*)"
    fi
    printf '  %-42s %6d lines\n' "${proj//\//_}/$name" "$(wc -l < "$target")"
}

PROJECTS="build/release device/xiaomi/onyx frameworks/base
packages/apps/Settings packages/apps/Updater
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
emit frameworks/base 0001-gesture-navbar-space.patch \
    core/java/android/provider/Settings.java \
    services/core/java/com/android/server/wm/DisplayPolicy.java

emit frameworks/base 0002-wallpaper-ai-spoof.patch \
    core/java/android/app/ActivityThread.java \
    core/java/android/security/pif/PlayIntegritySpoofService.java

emit frameworks/base 0003-lhdc-audio.patch \
    media/java/android/media/AudioSystem.java \
    services/core/java/com/android/server/audio/BtHelper.java

# Pixel lockscreen Now Playing, ported from Evolution-X c83186b. 53 files, all
# under packages/SystemUI, enumerated in a list rather than globbed: SystemUI is
# full of unrelated local churn, and `packages/SystemUI` as a pathspec would
# hoover it up. The list is authoritative -- regenerate it with
#   sed -n 's|^diff --git a/\(.*\) b/.*|\1|p' <the patch> | sort -u
# if the port grows a file.
NOWPLAYING_PATHS="${NOWPLAYING_PATHS:-$(dirname "${BASH_SOURCE[0]}")/nowplaying-paths.txt}"
[ -f "$NOWPLAYING_PATHS" ] || die "missing path list $NOWPLAYING_PATHS"
mapfile -t NP_PATHS < "$NOWPLAYING_PATHS"
[ "${#NP_PATHS[@]}" -eq 53 ] || die "expected 53 Now Playing paths, got ${#NP_PATHS[@]}"
emit frameworks/base 0004-pixel-lockscreen-now-playing.patch "${NP_PATHS[@]}"

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

emit packages/apps/Updater 0001-self-hosted-ota-url.patch \
    app/src/main/res/values/strings.xml

# --------------------------------------------------------------- vendor/xiaomi/onyx
# Only Android.mk. The 351MB of rebuilt radio/ images and the 2 byte-patched
# LHDC blobs ship as a separate overlay project (onyx-firmware) that apply.sh
# copies in -- they are binaries and have no business in a patch. Android.mk is
# text, so it stays a patch: if crDroid regenerates it upstream this conflicts
# loudly instead of being silently clobbered.
emit vendor/xiaomi/onyx 0001-firmware-sha1s-os3.0.302.0.patch Android.mk

echo
echo "Done. Totals:"
find "$OUT/patches" -name '*.patch' | wc -l | xargs echo "  patch files:"
du -sh "$OUT/patches" | awk '{print "  size:        "$1}'
