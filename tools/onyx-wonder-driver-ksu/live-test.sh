#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Source-only explicit helper; never installed in the KSU ZIP or run automatically.
[ "$#" = 2 ] && [ "$1" = --reviewed-live-test ] || {
    printf '%s\n' 'Usage: live-test.sh --reviewed-live-test /absolute/prepared-or-installed-module-dir' >&2
    exit 2
}
case "$2" in /*) WDR_MOD=$2;; *) exit 2;; esac
. "$WDR_MOD/common.sh" || exit 1
WDR_STAGE=live
wdr_init || exit 1
# Root must already stop Mosey APK/native and Wi-Fi HAL/supplicant, and disable Wi-Fi.
# This helper never changes the lifecycle of those services or zygote.
wdr_reload
