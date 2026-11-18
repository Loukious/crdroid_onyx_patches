#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
ONYX_MOD=${0%/*}
. "$ONYX_MOD/common.sh"
umask 077
mkdir -p "$ONYX_STATE"
exec >> "$ONYX_STATE/boot.log" 2>&1
[ -f "$ONYX_STATE/armed" ] || onyx_reject_before_mount 'Trial was not armed'
[ ! -f "$ONYX_STATE/failure" ] || onyx_reject_before_mount 'Failed trials require arm.sh'
previous=$(cat "$ONYX_STATE/prepared-boot" 2>/dev/null)
if [ -n "$previous" ] && [ "$previous" != "$(onyx_boot_id)" ]; then
    [ -f "$ONYX_STATE/accepted" ] \
        && [ "$(cat "$ONYX_STATE/health-verified-boot" 2>/dev/null)" = "$previous" ] \
        || onyx_reject_before_mount 'Previous brightness boot was not verified and accepted'
    if onyx_has_systemui; then
        [ "$(cat "$ONYX_STATE/systemui-verified-boot" 2>/dev/null)" = "$previous" ] \
            || onyx_reject_before_mount 'Previous SystemUI boot was not verified and accepted'
    fi
fi
[ -z "$(pidof zygote zygote64 system_server)" ] || onyx_reject_before_mount 'Framework already started'
onyx_check_assets || onyx_reject_before_mount 'Module scripts or metadata changed'
onyx_check_watchdog || onyx_reject_before_mount 'Independent watchdog scripts differ'
onyx_build_matches || onyx_reject_before_mount 'Base ROM changed'
onyx_check_visible "$ONYX_MOD/baseline.sha256" || onyx_reject_before_mount 'Base artifacts changed'
onyx_check_archive || onyx_reject_before_mount 'Archive payload changed'
onyx_boot_id > "$ONYX_STATE/prepared-boot"
date '+%m-%d %H:%M:%S.000' > "$ONYX_STATE/logcat-since"
sync
echo 'Brightness payload preflight passed before zygote'
