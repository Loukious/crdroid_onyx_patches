#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
. "${0%/*}/common.sh"
[ -f "$ONYX_STATE/armed" ] || exit 0
[ -d "$ONYX_MOD" ] && [ ! -f "$ONYX_MOD/remove" ] || exit 0
umask 077
exec >> "$ONYX_STATE/watchdog.log" 2>&1
boot=$(onyx_boot_id)
lock=$ONYX_STATE/watchdog-$boot.lock
mkdir "$lock" 2>/dev/null || exit 0
trap 'rmdir "$lock" 2>/dev/null' EXIT
if [ "$(cat "$ONYX_STATE/mounted-boot" 2>/dev/null)" != "$boot" ]; then
    if [ "$(cat "$ONYX_STATE/prepared-boot" 2>/dev/null)" = "$boot" ]; then
        onyx_fail_after_mount 'Preflight ran but the post-mount stage failed'
    fi
    echo 'No brightness mount in this boot; baseline remains active'
    exit 0
fi
echo $$ > "$ONYX_STATE/watchdog.pid"
count=0
while [ "$count" -lt 180 ]; do
    since=$(cat "$ONYX_STATE/logcat-since" 2>/dev/null)
    timeout 10 logcat -b crash -d -v threadtime -T "$since" \
        > "$ONYX_STATE/crashes.txt" 2>/dev/null
    if grep -Eq 'FATAL EXCEPTION IN SYSTEM PROCESS|>>> (system_server|zygote|zygote64) <<<|Process: system_server,' \
            "$ONYX_STATE/crashes.txt"; then
        onyx_fail_after_mount 'System server or zygote crashed during the brightness trial'
    fi
    if onyx_has_systemui \
            && grep -Eq 'Process: com\.android\.systemui([,:]|$)|>>> com\.android\.systemui(:[^ ]+)? <<<' \
                "$ONYX_STATE/crashes.txt"; then
        onyx_fail_after_mount 'SystemUI crashed during the brightness trial'
    fi
    if [ "$(getprop sys.boot_completed)" = 1 ] && [ -n "$(pidof system_server)" ] \
            && { ! onyx_has_systemui || [ -n "$(pidof com.android.systemui)" ]; }; then
        if [ "$(cat "$ONYX_STATE/health-verified-boot" 2>/dev/null)" != "$boot" ]; then
            timeout 20 dumpsys display > "$ONYX_STATE/display.txt" 2>&1 \
                || onyx_fail_after_mount 'Display service did not answer within twenty seconds'
            grep -Fq 'Onyx sensors:' "$ONYX_STATE/display.txt" \
                || onyx_fail_after_mount 'Boot completed without the brightness port marker'
            onyx_check_visible "$ONYX_MOD/payload.sha256" \
                || onyx_fail_after_mount 'Payload hashes changed after boot'
            onyx_check_systemui \
                || onyx_fail_after_mount 'SystemUI process or service did not verify within twenty seconds'
            if onyx_has_systemui; then
                onyx_boot_id > "$ONYX_STATE/systemui-verified-boot"
            fi
            onyx_boot_id > "$ONYX_STATE/health-verified-boot"
            echo 'Framework booted with Onyx sensor policy; awaiting acceptance'
        fi
        if [ -f "$ONYX_STATE/accepted" ]; then
            echo 'Accepted brightness trial remains enabled'
            exit 0
        fi
    elif [ "$count" -ge 60 ]; then
        onyx_fail_after_mount 'Android or required SystemUI did not complete boot within five minutes'
    fi
    sleep 5
    count=$((count + 1))
done
onyx_fail_after_mount 'Brightness trial was not accepted within fifteen minutes'
