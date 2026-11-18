#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
ONYX_MOD=${0%/*}
. "$ONYX_MOD/common.sh"
umask 077
exec >> "$ONYX_STATE/boot.log" 2>&1
# This boot retains its mounts; an unaccepted trial's next boot uses the baseline.
[ -f "$ONYX_STATE/accepted" ] || touch "$ONYX_MOD/disable"
sync
[ "$(cat "$ONYX_STATE/prepared-boot" 2>/dev/null)" = "$(onyx_boot_id)" ] \
    || onyx_fail_after_mount 'Preflight did not run in this boot'
[ -z "$(pidof zygote zygote64 system_server)" ] \
    || onyx_fail_after_mount 'Payload mounted after framework startup'
onyx_check_visible "$ONYX_MOD/payload.sha256" \
    || onyx_fail_after_mount 'Mounted brightness or SystemUI files differ'
onyx_boot_id > "$ONYX_STATE/mounted-boot"
sync
# Start immediately; service.d provides a fallback entry if this child exits early.
"$ONYX_BUSYBOX" setsid /system/bin/sh "$ONYX_STATE/guard-service.sh" \
    </dev/null >> "$ONYX_STATE/guard-launch.log" 2>&1 &
echo 'Mounted brightness trial; detached watcher will verify startup'
