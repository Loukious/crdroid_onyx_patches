#!/usr/bin/env bash
#
# Generate the Evolution X onyx patch set from the working tree at $ROM.
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
    # without either patch carrying the other's hunks. No patch needs either knob
    # today -- both are kept because the moment a feature gets committed locally
    # instead of left dirty, a plain `git diff` goes blind to it again.
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
packages/apps/Settings packages/apps/Updater packages/apps/Evolver
packages/modules/Bluetooth packages/modules/common
vendor/lineage vendor/qcom/opensource/interfaces
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
# Settings.java carries only GESTURE_NAVBAR_SPACE_MODE now, so no hunk filter.
emit frameworks/base 0001-gesture-navbar-space.patch \
    core/java/android/provider/Settings.java \
    services/core/java/com/android/server/wm/DisplayPolicy.java

# The AI-Wallpapers spoof is gone: Evo's config-driven PIF can spoof any app
# from its JSON config (Settings.Secure), so a dedicated patch is redundant.
emit frameworks/base 0002-lhdc-audio.patch \
    media/java/android/media/AudioSystem.java \
    services/core/java/com/android/server/audio/BtHelper.java

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

# Evo ships bcr as a prebuilt in vendor/extras (wired by its own
# vendor/lineage/config/telephony.mk), so crDroid's vendor/bcr must not be
# synced -- but the device tree still inherits vendor/bcr/bcr.mk, which would
# fail on the missing project. Remove the inherit; the app still ships.
emit device/xiaomi/onyx 0005-drop-crdroid-bcr.patch device.mk

# ------------------------------------------------------------------- vendor/lineage
emit vendor/lineage 0001-kernel-bin-override.patch build/tasks/kernel.mk

# ------------------------------------------------------- packages/apps/Settings
# The UI half of gesture-navbar-space: one ListPreference in the gesture-nav
# screen. Under Evolution X this is XML only -- Evo's
# org.evolution.settings.preferences.SystemSettingListPreference persists the
# value to Settings.System itself, so the 43 lines of Java the crDroid version
# needed (initGestureNavbarSpacePreference + constants + listener) are gone.
# Do not add them back; a preference class doing the write is what Evo does for
# every other system setting, and it is one less thing to rebase.
emit packages/apps/Settings 0001-gesture-navbar-space-ui.patch \
    res/xml/gesture_navigation_settings.xml

emit packages/apps/Updater 0001-self-hosted-ota-url.patch \
    app/src/main/res/values/strings.xml

# ----------------------------------------------------------------- Evolver
# Strings and arrays for the gesture-navbar-space preference. They have to live
# here, not in packages/apps/Settings: Evo builds Evolver *into* the Settings
# APK (Settings/Android.bp: "Evolver/res" in resource_dirs, --extra-packages
# org.evolution.settings), which is why an @string reference from
# res/xml/gesture_navigation_settings.xml resolves against Evolver's resources.
# Evo splits strings and arrays across two files, so both are listed.
emit packages/apps/Evolver 0001-gesture-navbar-space-ui.patch \
    res/values/evolution_strings.xml \
    res/values/evolution_arrays.xml

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
