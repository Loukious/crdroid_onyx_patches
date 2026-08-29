#!/usr/bin/env bash
#
# Sync + patch + build Evolution X 16 (bka) for onyx (POCO F7).
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
MANIFEST_BRANCH="${MANIFEST_BRANCH:-bka}"
LOCAL_MANIFESTS="${LOCAL_MANIFESTS:-https://github.com/Loukious/local_manifests_onyx}"
LOCAL_MANIFESTS_BRANCH="${LOCAL_MANIFESTS_BRANCH:-evolution-bka}"
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

# ---------------------------------------------------------------------- build
# installclean, NOT `make clean` / `rm -rf out`: it drops the installed image
# staging without throwing away the object cache the queue depends on.
say "make installclean"
make installclean || { echo "FATAL: installclean failed"; exit 1; }

say "mka evolution"
mka evolution
rc=$?
if [ "$rc" -ne 0 ]; then
    echo "FATAL: mka evolution failed (exit $rc)"
    exit "$rc"
fi

say "artifacts"
ls -lh "out/target/product/$DEVICE"/*.zip 2>/dev/null || true
