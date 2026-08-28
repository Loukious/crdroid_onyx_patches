#!/usr/bin/env bash
#
# Local compile gate -- run this BEFORE pushing / dispatching a crave build.
#
# Why it exists: crave queue time is hours, and a broken patch surfaces only
# after that wait (build 295615 burned ~4h to report one unresolved symbol).
# Compiling the affected module locally costs minutes and catches the whole
# class of "the port references an API this tree does not have".
#
# Low-RAM box: -j3 is the validated setting. Do not raise it blindly; SystemUI
# kapt/kotlinc peak several GB per worker.
#
# Usage:  ci/local-compile-check.sh [/path/to/rom] [soong target ...]
#   e.g.  ci/local-compile-check.sh ~/android/crdroid SystemUI
# Default target is SystemUI-core (the module the SystemUI patches break first).
#
# NOTE: no `set -e`, no `set -u`, no `pipefail` anywhere in this script -- see
# the block above the `source build/envsetup.sh` line for why. Every command
# that matters is checked explicitly instead.

ROM="${1:-${ROM:-$HOME/android/crdroid}}"
if [ -d "$ROM/build/make" ]; then shift; else ROM="${ROM:-$HOME/android/crdroid}"; fi
JOBS="${JOBS:-3}"
LUNCH="${LUNCH:-lineage_onyx-bp4a-userdebug}"
TARGETS=("$@")
[ "${#TARGETS[@]}" -gt 0 ] || TARGETS=(SystemUI-core)

red() { printf '\033[0;31m%s\033[0m\n' "$*"; }
grn() { printf '\033[0;32m%s\033[0m\n' "$*"; }

cd "$ROM" || { red "FATAL: no such ROM tree: $ROM"; exit 1; }
[ -f build/envsetup.sh ] || { red "FATAL: $ROM is not an Android tree (no build/envsetup.sh)"; exit 1; }

# Strict-shell options must be OFF before envsetup and stay off, exactly as in
# ci/crave-build.sh:
#   * -u          build/envsetup.sh:21 reads $TOP with no :- guard -> "TOP:
#                 unbound variable". This killed crave build 295490, and it
#                 killed the first version of this script too.
#   * -e/pipefail vendor/lineage/build/envsetup.sh:1020 pipes /dev/urandom into
#                 head; head exits early, cat takes SIGPIPE, pipefail reports
#                 141, -e kills the script.
set +u
set +e
set +o pipefail

# shellcheck disable=SC1091
source build/envsetup.sh > /tmp/envsetup.log 2>&1 || {
    red "FATAL: envsetup.sh failed"; tail -20 /tmp/envsetup.log; exit 1; }

# CRITICAL: never pipe `lunch`. A pipe runs it in a SUBSHELL, so its exports
# (TARGET_RELEASE, TARGET_PRODUCT) never reach this shell and the build dies with
#   "No release config set for target ... where release is one of: ."
# even though bp4a is defined correctly in all three release_config_map.textproto.
# Redirection is fine; a pipe is not.
lunch "$LUNCH" > /tmp/lunch.log 2>&1
if [ -z "$TARGET_RELEASE" ] || [ -z "$TARGET_PRODUCT" ]; then
    red "FATAL: lunch '$LUNCH' did not export TARGET_RELEASE/TARGET_PRODUCT"
    tail -25 /tmp/lunch.log
    exit 1
fi
grn "lunch ok: TARGET_PRODUCT=$TARGET_PRODUCT TARGET_RELEASE=$TARGET_RELEASE"

echo "### m -j$JOBS ${TARGETS[*]}   (started $(date -u +%H:%M:%SZ))"
m -j"$JOBS" "${TARGETS[@]}"
rc=$?
echo "### finished $(date -u +%H:%M:%SZ)"
if [ "$rc" -eq 0 ]; then
    grn "LOCAL COMPILE PASSED: ${TARGETS[*]}  -- safe to push and dispatch crave"
else
    red "LOCAL COMPILE FAILED (rc=$rc): ${TARGETS[*]}  -- fix before pushing"
fi
exit "$rc"
