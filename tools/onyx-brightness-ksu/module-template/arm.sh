#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
ONYX_MOD=${0%/*}
. "$ONYX_MOD/common.sh"
set -e
umask 077
onyx_build_matches
onyx_check_assets
onyx_check_archive
onyx_check_visible "$ONYX_MOD/baseline.sha256"
onyx_check_watchdog
onyx_label_payload
[ ! -f "$ONYX_MOD/remove" ]
mkdir -p "$ONYX_STATE"
rm -f "$ONYX_STATE/failure" "$ONYX_STATE/accepted" "$ONYX_STATE/prepared-boot" \
    "$ONYX_STATE/mounted-boot" "$ONYX_STATE/health-verified-boot" "$ONYX_STATE/systemui-verified-boot"
touch "$ONYX_STATE/armed"
"$ONYX_KSUD" module enable "$ONYX_ID"
# A normal KernelSU install stages this script in modules_update until reboot.
rm -f "$ONYX_MOD/disable"
sync
echo 'Brightness trial armed for the next full reboot'
