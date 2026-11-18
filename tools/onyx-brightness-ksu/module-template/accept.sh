#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
ONYX_MOD=${0%/*}
. "$ONYX_MOD/common.sh"
set -e
boot=$(onyx_boot_id)
[ ! -f "$ONYX_STATE/failure" ]
[ "$(cat "$ONYX_STATE/mounted-boot")" = "$boot" ]
[ "$(cat "$ONYX_STATE/health-verified-boot")" = "$boot" ]
[ "$(getprop sys.boot_completed)" = 1 ]
[ "$(getenforce)" = Enforcing ]
onyx_manifest_contract
onyx_check_visible "$ONYX_MOD/payload.sha256"
if onyx_has_systemui; then
    [ "$(cat "$ONYX_STATE/systemui-verified-boot")" = "$boot" ]
    onyx_check_systemui
fi
"$ONYX_KSUD" module enable "$ONYX_ID"
touch "$ONYX_STATE/accepted"
sync
echo 'Verified brightness trial enabled for subsequent boots'
