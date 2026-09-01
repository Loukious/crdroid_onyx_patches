#!/usr/bin/env bash
#
# Sync + patch + build Evolution X for onyx (POCO F7).
#
# Branch evolution-cnb of this repo = EXPERIMENTAL Android 17 (Evolution X
# 'cnb') on top of the unchanged 16.0 device-side stack, because no onyx
# device tree exists at 17.0 yet. The A16 recipe lives on the evolution-bka
# branch; keep both in mind when porting fixes between them.
#
# This runs ON A CRAVE BUILD SERVER, with the working directory set to the ROM
# source root -- never in the Devspace CLI, where `repo sync` and `make` are
# against the rules (https://github.com/FOSSonTop/crave/blob/master/rules.md).
# It is invoked by .github/workflows/crdroid-onyx.yml as:
#
#   crave run --projectID 93 --no-patch -- "<clone this repo> && bash ci/crave-build.sh"
#
# Keeping the recipe here rather than inline in the workflow means it is
# reviewable in git, editable without touching CI, and the crave command string
# stays short enough to have no quoting hazards.
#
# env:
#   SYNC_ONLY=1          sync + patch + breakfast, then stop before compiling
#   KERNEL_RELEASE_TAG   konoha-kernel-gki release to take the Image from
#   DEVICE               default onyx
#   BUILD_USERNAME       stamped into the build fingerprint
#
set -euo pipefail

MANIFEST_URL="${MANIFEST_URL:-https://github.com/Evolution-X/manifest.git}"
MANIFEST_BRANCH="${MANIFEST_BRANCH:-cnb}"
LOCAL_MANIFESTS="${LOCAL_MANIFESTS:-https://github.com/Loukious/local_manifests_onyx}"
LOCAL_MANIFESTS_BRANCH="${LOCAL_MANIFESTS_BRANCH:-evolution-cnb}"
DEVICE="${DEVICE:-onyx}"
SYNC_ONLY="${SYNC_ONLY:-0}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say() { printf '\n\033[1;36m>> %s\033[0m\n' "$*"; }

[ -d .repo ] || { echo "FATAL: $(pwd) is not a repo workspace"; exit 1; }

# ------------------------------------------------------------------- manifest
# Only .repo/local_manifests is removed. Never `rm -rf *` and never touch out/
# -- wiping the pre-synced source turns a 30 min incremental into a 4 hour
# rebuild and makes the whole queue wait.
say "re-pointing the workspace at Evolution X $MANIFEST_BRANCH"

# Switching ROMs/branches makes repo DELETE every project the new manifest
# doesn't carry, and repo refuses to remove a project that still has local
# changes -- build 296809 died exactly there (arm-linux-androideabi-4.9,
# leftover crDroid-16 state, after resync.sh had already nuked nine patched
# repos to work around the same thing). Reset everything under the OLD
# manifest first, while it still lists these projects, so the sync can move
# or drop them freely. Nothing is lost: apply.sh re-creates every local
# change on the new tree.
repo forall -j8 -c 'git reset --hard && git clean -fd' >/dev/null 2>&1 || true

rm -rf .repo/local_manifests

# --depth 1 is requested by the crave rules to cut sync time. It also makes the
# kernel/xiaomi/sm8735* projects shallow, so scripts/setlocalversion falls back
# to a bare SHA instead of a tag-derived version string. That is harmless here:
# the Image that actually gets installed comes from Kono-Ha, not from this
# source tree (see vendor/extra/BoardConfigKernel.mk).
repo init -u "$MANIFEST_URL" -b "$MANIFEST_BRANCH" --git-lfs --depth 1

git clone --depth 1 -b "$LOCAL_MANIFESTS_BRANCH" "$LOCAL_MANIFESTS" .repo/local_manifests

# ----------------------------------------------------------------------- sync
# crave's resync.sh is what the docs ask for instead of a bare `repo sync`: it
# resolves the conflicts that come from uncommitted changes and from a
# workspace that was last synced against a different ROM.
say "syncing"
if   [ -x /usr/bin/resync ];      then /usr/bin/resync
elif [ -x /opt/crave/resync.sh ]; then /opt/crave/resync.sh
else
    echo "note: no resync script on this node, falling back to repo sync"
    repo sync -c --force-sync --no-clone-bundle --no-tags -j"$(nproc)"
fi

# -------------------------------------------------------------------- patches
# Patch set + OS3.0.302.0 firmware overlay + the Kono-Ha kernel Image.
# apply.sh is idempotent and exits non-zero on a genuine failure, so a
# half-patched tree can never reach mka.
say "applying the onyx patch set"
"$HERE/apply.sh" .

# Fast symbol gate. ~25s, and it runs here -- right after sync, before the
# multi-hour compile -- because that is the only place it saves anything.
# It indexes every simple name declared in the tree and checks every in-tree
# import the patch set adds against that index. Build 295615 died 38% into a 4h
# compile (after a 3h queue) on exactly one missing symbol,
# BaseLockscreenElement.ElementSource: a since-removed SystemUI port came from
# Evolution-X, whose lockscreen plugin API has that nested type, and crDroid's
# tree predates it. This check reports that in seconds instead.
# HERE is the repo root (apply.sh lives there), but check-imports.sh sits in
# ci/ next to its import-allowlist.txt. Run 33244376173 died at this line with
# "/tmp/onyx-ci/check-imports.sh: No such file or directory" -- the script had
# only ever been invoked directly as ci/check-imports.sh, never through HERE.
say "checking patched imports resolve against this tree"
"$HERE/ci/check-imports.sh" .

# ------------------------------------------------------------------ configure
# NOTE: BUILD_USERNAME / BUILD_HOSTNAME are deliberately *not* set here.
# vendor/lineage/build/envsetup.sh:1017 generate_host_overrides() runs at source
# time and unconditionally overwrites both with android-build / r-<random>,
# exactly as crDroid's own release builds do. Exporting them before sourcing is
# dead code, and forcing them afterwards would only leak the builder identity
# into ro.build.{user,host}. The maintainer name users actually see comes from
# the release builds. There is no maintainer prop under Evo (see README).

say "breakfast $DEVICE userdebug"
# The strict-shell options have to come off before envsetup, and stay off for
# the rest of the script. Two separate landmines, both confirmed by hand
# against this tree:
#
#   * -u    build/envsetup.sh:21 is `if [ -n "$TOP" -a -f "$TOP/$TOPFILE" ]`
#           with no :- guard, so under -u it aborts instantly with
#           "build/envsetup.sh: line 21: TOP: unbound variable". That is what
#           killed crave build 295490.
#   * -e + pipefail
#           vendor/lineage/build/envsetup.sh:1020 is
#           `cat /dev/urandom | tr -dc 'a-z0-9' | head -c 4`. head exits after
#           4 bytes, cat takes SIGPIPE, pipefail reports 141, -e kills the
#           script. Fixing only -u just moves the failure three seconds later.
#
# Nor is re-arming them afterwards worth it: envsetup, lunch, breakfast,
# soong_ui and the vendor hooks all read unset variables and pipe into head as
# a matter of course. So every command that matters from here on is checked
# explicitly instead.
set +u
set +e
set +o pipefail

# shellcheck disable=SC1091
source build/envsetup.sh || { echo "FATAL: envsetup failed"; exit 1; }
breakfast "$DEVICE" userdebug || { echo "FATAL: breakfast $DEVICE failed"; exit 1; }

# Cheap sanity check on the two things most likely to be silently wrong: the
# Android 16 release config, and whether the LHDC aconfig flag actually landed.
cfg="out/soong/release-config/args-lineage_${DEVICE}.txt"
if [ -f "$cfg" ]; then
    say "release config"
    tr ' ' '\n' < "$cfg" | grep -iE 'TARGET_RELEASE|lhdc' || true
fi

if [ "$SYNC_ONLY" = "1" ]; then
    say "SYNC_ONLY=1 -- stopping before the compile"
    exit 0
fi

# ------------------------------------------------------------------ konoha ABI
# qcacld-3.0 builds against the Kono-Ha kernel ABI, prepared on demand by
# konoha-abi-prep.sh. mka invokes it from inside a build action, where soong's
# hermetic PATH replaces curl with a stub that refuses to run ("curl is not
# allowed to be used", Changes.md#PATH_Tools) -- build 33259303359 died at 99%
# on exactly that. Run the whole prep HERE, in the recipe shell where curl and
# git work normally; the stamp file it writes then makes the in-build
# invocation a no-op. clang comes from the tree explicitly: the script's
# /usr/lib/llvm-* fallback does not exist on the build servers. This is still
# a crave run on the build server, not a Devspace build -- the rules only
# forbid make/mka in the Devspace CLI.
say "preparing the Kono-Ha kernel-ABI tree (before mka)"
prep="kernel/xiaomi/sm8735-modules/qcom/opensource/wlan/qcacld-3.0/konoha-abi-prep.sh"
[ -f "$prep" ] || { echo "FATAL: $prep missing (wlan overlay did not land?)"; exit 1; }
clang_bin="$(ls -d prebuilts/clang/host/linux-x86/clang-*/bin 2>/dev/null | sort -V | tail -1)"
[ -n "$clang_bin" ] || { echo "FATAL: no prebuilts/clang/host/linux-x86/clang-* found"; exit 1; }
CLANG_PATH="$PWD/$clang_bin" bash "$prep" || { echo "FATAL: konoha-abi prep failed"; exit 1; }

# ---------------------------------------------------------------------- build
# installclean, NOT `make clean` / `rm -rf out`: it drops the installed image
# staging without throwing away the object cache the queue depends on.
say "make installclean"
make installclean || { echo "FATAL: installclean failed"; exit 1; }

# Postmortem of crave build 296544 (the 2026-08-31 OTA that bootlooped and
# Virtual-A/B-rolled-back): on a resumed out/ ninja can consider the kernel
# Image edge clean -- the kernel make finds everything up to date and does not
# rewrite the Image, so its mtime never advances ("ninja: Missing restat?"
# in that job's log) -- while installclean has wiped the module staging dirs.
# The vendor_boot / vendor_dlkm packing edges depend on the Image *file*, see
# it as clean, and pack from the module-less staging long before the kernel
# recipe (Image edge, dirty via .config) gets around to reinstalling the 574
# modules and appending them to the file lists. The result passed mka with
# exit 0 and shipped a vendor_boot ramdisk with 0 .ko files (33 cpio entries
# vs 422 on the known-good build) and a ~340 KB vendor_dlkm.img (32 MB good).
#
# Deleting .config and the Image makes the kernel edge dirty from graph load,
# so every packing edge that depends on it waits for module install first;
# deleting the packed outputs means restat cannot resurrect a stale pack.
# Cost: one kernel relink on an incremental build, nothing on a clean one.
#
# Postmortem of job 296582 (the 2026-08-31 run-17 OTA that STILL bootlooped
# with this scrub in place): the OTA payload's vendor_boot is not the loose
# out/.../vendor_boot.img at all -- add_img_to_target_files REBUILDS it via
# mkbootfs from its own staging tree, .../lineage_onyx-target_files/
# VENDOR_BOOT/RAMDISK, which is snapshotted from out/.../vendor_ramdisk/ at
# whatever moment ninja schedules the target-files edge. In that job the edge
# started at 13:51:28, nine seconds after the kernel's module INSTALL
# (13:51:19) and before the modules had been distributed into vendor_ramdisk/
# -- so the staged tree was module-less, the payload shipped 0 .ko, and the
# phone bootlooped, while the loose vendor_boot.img (packed later, at
# 13:55:36, from the by-then-populated staging) passed the verify gate. Two
# consequences:
#   1. the scrub also deletes the target-files staging tree AND zip AND the
#      old OTA zips, so no output from a previous job can survive into this
#      one, and
#   2. the race itself is scheduler luck that no scrub can prevent, so when
#      the (now zip-aware) verify gate fails, we scrub and build ONE more
#      pass: by then vendor_ramdisk/ is fully populated, so the re-staged
#      tree and the repacked images both contain the modules.
PRODUCT_OUT="out/target/product/$DEVICE"
KERNEL_OBJ="$PRODUCT_OUT/obj/KERNEL_OBJ"

scrub() {
    say "scrubbing stale kernel/packing state from the previous run"
    rm -f "$KERNEL_OBJ/.config" \
          "$KERNEL_OBJ/arch/arm64/boot/Image" \
          "$PRODUCT_OUT/obj/PACKAGING/vendor_boot_intermediates/vendor_ramdisk.cpio" \
          "$PRODUCT_OUT/obj/PACKAGING/vendor_boot_intermediates/vendor_ramdisk.cpio.lz4" \
          "$PRODUCT_OUT/vendor_boot.img" \
          "$PRODUCT_OUT/vendor_ramdisk.img" \
          "$PRODUCT_OUT/vendor_dlkm.img" \
          "$PRODUCT_OUT/system_dlkm.img" \
          "$PRODUCT_OUT/obj/PACKAGING/target_files_intermediates"/lineage_onyx-target_files.zip \
          "$PRODUCT_OUT"/EvolutionX-*.zip
    rm -rf "$PRODUCT_OUT/obj/PACKAGING/target_files_intermediates"/lineage_onyx-target_files
}

scrub

say "mka evolution"
mka evolution
rc=$?
if [ "$rc" -ne 0 ]; then
    echo "FATAL: mka evolution failed (exit $rc)"
    exit "$rc"
fi

# The failure above is invisible to the build system -- mka exits 0 with the
# modules missing -- so gate the artifacts on what actually got packed,
# INCLUDING the images inside the shipped OTA zip's payload.bin (what the
# phone's update_engine would write; see ci/verify-payload.py). This must run
# before the workflow's pull/publish steps ever see a zip.
say "verifying the packed images"
if ! "$HERE/ci/verify-images.sh" "$PWD"; then
    say "verification failed -- repacking once from the now-populated staging"
    scrub
    say "mka evolution (second pass)"
    mka evolution
    rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "FATAL: second-pass mka evolution failed (exit $rc)"
        exit "$rc"
    fi
    say "verifying the packed images (second pass)"
    "$HERE/ci/verify-images.sh" "$PWD" || {
        echo "FATAL: image verification failed twice -- refusing to ship this build"
        exit 1
    }
fi

say "artifacts"
ls -lh "out/target/product/$DEVICE"/*.zip 2>/dev/null || true
