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
    git -C "$ROM/$proj" diff --no-color --no-renames --binary -- "$@" > "$target"
    if [ ! -s "$target" ]; then
        rm -f "$target"
        die "$proj: patch $name came out EMPTY (pathspec: $*)"
    fi
    printf '  %-42s %6d lines\n' "${proj//\//_}/$name" "$(wc -l < "$target")"
}

PROJECTS="build/release device/xiaomi/onyx frameworks/base
packages/modules/Bluetooth packages/modules/common vendor/lineage
vendor/pixel/launcher vendor/qcom/opensource/interfaces vendor/xiaomi/onyx"

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

# The Pixel Lockscreen Now Playing port (Evolution-X c83186b, reverse-engineered
# from CP2A SystemUIGoogle) plus the two integration points that had to be
# re-done by hand for crDroid: SystemUICoreStartableModule.kt (crDroid's import
# block differs) and DefaultBlueprint.kt (crDroid assembles compose lockscreen
# element providers through createRemembered(vararg) rather than Evolution-X's
# ElementProviderModule dagger multibind, which crDroid does not have).
#
# The pathspec is enumerated rather than globbed: `packages/SystemUI/res` would
# happily swallow any unrelated SystemUI resource edit sitting in the tree.
emit frameworks/base 0004-pixel-lockscreen-now-playing.patch \
    packages/SystemUI/AndroidManifest.xml \
    packages/SystemUI/compose/features/src/com/android/systemui/keyguard/ui/composable/blueprint/DefaultBlueprint.kt \
    packages/SystemUI/res/anim/audioanim_animation.xml \
    packages/SystemUI/res/color/bg_smartspace_card_solid.xml \
    packages/SystemUI/res/drawable/avd_nowplaying_searching.xml \
    packages/SystemUI/res/drawable/bg_smartspace_action_button.xml \
    packages/SystemUI/res/drawable/bg_smartspace_card.xml \
    packages/SystemUI/res/drawable/ic_cloud_off.xml \
    packages/SystemUI/res/drawable/ic_error.xml \
    packages/SystemUI/res/drawable/ic_favorite.xml \
    packages/SystemUI/res/drawable/ic_favorite_border.xml \
    packages/SystemUI/res/drawable/ic_favorite_note.xml \
    packages/SystemUI/res/drawable/ic_music_not_found.xml \
    packages/SystemUI/res/drawable/ic_music_search.xml \
    packages/SystemUI/res/drawable/ic_now_playing_heart_minus.xml \
    packages/SystemUI/res/drawable/ic_now_playing_heart_plus.xml \
    packages/SystemUI/res/drawable/ic_now_playing_lockscreen.xml \
    packages/SystemUI/res/drawable/ic_now_playing_music_note.xml \
    packages/SystemUI/res/drawable/ic_now_playing_music_off.xml \
    packages/SystemUI/res/drawable/rounded_rectangle_20dp.xml \
    packages/SystemUI/res/drawable/vd_nowplaying_iconsearch_v2.xml \
    packages/SystemUI/res/interpolator/even.xml \
    packages/SystemUI/res/layout/ambient_indication.xml \
    packages/SystemUI/res/layout/ambient_indication_inner.xml \
    packages/SystemUI/res/values-h650dp/ambientindication_dimens.xml \
    packages/SystemUI/res/values-h700dp/ambientindication_dimens.xml \
    packages/SystemUI/res/values-h800dp/ambientindication_dimens.xml \
    packages/SystemUI/res/values-sw600dp-land/ambientindication_dimens.xml \
    packages/SystemUI/res/values/ambientindication_colors.xml \
    packages/SystemUI/res/values/ambientindication_dimens.xml \
    packages/SystemUI/res/values/ambientindication_strings.xml \
    packages/SystemUI/res/xml/ambient_indication_inner_downwards.xml \
    packages/SystemUI/res/xml/ambient_indication_inner_upwards.xml \
    packages/SystemUI/src/com/android/systemui/dagger/SystemUICoreStartableModule.kt \
    packages/SystemUI/src/com/android/systemui/dagger/SystemUIModule.java \
    packages/SystemUI/src/com/android/systemui/keyguard/data/quickaffordance/KeyguardDataQuickAffordanceModule.kt \
    packages/SystemUI/src/com/google/android/systemui/ambientmusic/AmbientIndicationAnimationHelper.kt \
    packages/SystemUI/src/com/google/android/systemui/ambientmusic/AmbientIndicationAnimationUtils.kt \
    packages/SystemUI/src/com/google/android/systemui/ambientmusic/AmbientIndicationArtworkHelper.kt \
    packages/SystemUI/src/com/google/android/systemui/ambientmusic/AmbientIndicationContainer.kt \
    packages/SystemUI/src/com/google/android/systemui/ambientmusic/AmbientIndicationService.kt \
    packages/SystemUI/src/com/google/android/systemui/keyguard/AmbientIndicationCoreStartable.kt \
    packages/SystemUI/src/com/google/android/systemui/keyguard/data/quickaffordance/NowPlayingQuickAffordanceConfig.kt \
    packages/SystemUI/src/com/google/android/systemui/keyguard/data/repository/AmbientIndicationRepository.kt \
    packages/SystemUI/src/com/google/android/systemui/keyguard/domain/interactor/AmbientIndicationInteractor.kt \
    packages/SystemUI/src/com/google/android/systemui/keyguard/shared/AmbientIndicationMusic.kt \
    packages/SystemUI/src/com/google/android/systemui/keyguard/shared/AmbientIndicationMusicStatus.kt \
    packages/SystemUI/src/com/google/android/systemui/keyguard/shared/ExpandedIndicationData.kt \
    packages/SystemUI/src/com/google/android/systemui/keyguard/shared/ExtendedIndication.kt \
    packages/SystemUI/src/com/google/android/systemui/keyguard/ui/binder/KeyguardAmbientIndicationAreaViewBinder.kt \
    packages/SystemUI/src/com/google/android/systemui/keyguard/ui/composable/elements/GoogleAmbientIndicationElementProvider.kt \
    packages/SystemUI/src/com/google/android/systemui/keyguard/ui/sections/DefaultAmbientIndicationAreaSection.kt \
    packages/SystemUI/src/com/google/android/systemui/keyguard/ui/viewmodel/KeyguardAmbientIndicationViewModel.kt

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
