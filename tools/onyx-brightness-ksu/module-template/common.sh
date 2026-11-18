#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
ONYX_ID=onyx_stock_brightness_test
ONYX_MOD=${ONYX_MOD:-/data/adb/modules/$ONYX_ID}
ONYX_STATE=${ONYX_STATE:-/data/adb/onyx-stock-brightness-test}
ONYX_WATCHER=${ONYX_WATCHER:-/data/adb/service.d/91-onyx-stock-brightness-test.sh}
ONYX_KSUD=${ONYX_KSUD:-/data/adb/ksud}
ONYX_REBOOT=${ONYX_REBOOT:-/system/bin/reboot}
ONYX_BUSYBOX=${ONYX_BUSYBOX:-/data/adb/ksu/bin/busybox}
ONYX_SYSTEMUI=/system_ext/priv-app/SystemUIGoogle/SystemUIGoogle.apk
ONYX_SYSTEMUI_ARCHIVE=system/system_ext/priv-app/SystemUIGoogle/SystemUIGoogle.apk

onyx_boot_id() { cat /proc/sys/kernel/random/boot_id; }
onyx_manifest_format() (
    [ -s "$1" ] || return 1
    seen_services=0; seen_panel_a=0; seen_panel_b=0; seen_systemui=0
    while IFS= read -r line || [ -n "$line" ]; do
        hash=${line%% *}
        path=${line#"$hash  "}
        [ "${#hash}" = 64 ] && [ "$line" = "$hash  $path" ] || return 1
        case "$hash" in *[!0-9a-f]*) return 1;; esac
        case "$path" in
            /system/framework/services.jar)
                [ "$seen_services" = 0 ] || return 1; seen_services=1;;
            /vendor/etc/displayconfig/display_id_4630947173316895379.xml)
                [ "$seen_panel_a" = 0 ] || return 1; seen_panel_a=1;;
            /vendor/etc/displayconfig/display_id_4630947258895476883.xml)
                [ "$seen_panel_b" = 0 ] || return 1; seen_panel_b=1;;
            "$ONYX_SYSTEMUI")
                [ "$seen_systemui" = 0 ] || return 1; seen_systemui=1;;
            *) return 1;;
        esac
    done < "$1"
    [ "$seen_services$seen_panel_a$seen_panel_b" = 111 ]
)
onyx_has_systemui() {
    grep -Fq "  $ONYX_SYSTEMUI" "${1:-$ONYX_MOD/payload.sha256}"
}
onyx_manifest_contract() (
    onyx_manifest_format "$ONYX_MOD/baseline.sha256" \
        && onyx_manifest_format "$ONYX_MOD/payload.sha256" || return 1
    if onyx_has_systemui "$ONYX_MOD/baseline.sha256"; then
        onyx_has_systemui || return 1
    else
        ! onyx_has_systemui || return 1
    fi
    [ -s "$ONYX_MOD/archive-payload.sha256" ] || return 1
    seen_services=0; seen_panel_a=0; seen_panel_b=0; seen_systemui=0
    while IFS= read -r line || [ -n "$line" ]; do
        hash=${line%% *}
        path=${line#"$hash  "}
        [ "${#hash}" = 64 ] && [ "$line" = "$hash  $path" ] || return 1
        case "$hash" in *[!0-9a-f]*) return 1;; esac
        installed=/$path
        case "$path" in
            system/framework/services.jar)
                [ "$seen_services" = 0 ] || return 1; seen_services=1;;
            vendor/etc/displayconfig/display_id_4630947173316895379.xml)
                [ "$seen_panel_a" = 0 ] || return 1; seen_panel_a=1;;
            vendor/etc/displayconfig/display_id_4630947258895476883.xml)
                [ "$seen_panel_b" = 0 ] || return 1; seen_panel_b=1;;
            "$ONYX_SYSTEMUI_ARCHIVE")
                [ "$seen_systemui" = 0 ] || return 1; seen_systemui=1
                installed=$ONYX_SYSTEMUI;;
            *) return 1;;
        esac
        grep -Fxq "$hash  $installed" "$ONYX_MOD/payload.sha256" || return 1
    done < "$ONYX_MOD/archive-payload.sha256"
    [ "$seen_services$seen_panel_a$seen_panel_b" = 111 ] || return 1
    if onyx_has_systemui; then
        [ "$seen_systemui" = 1 ]
    else
        [ "$seen_systemui" = 0 ]
    fi
)
onyx_check_systemui() {
    onyx_has_systemui || return 0
    [ -n "$(pidof com.android.systemui)" ] || return 1
    timeout 20 dumpsys activity service com.android.systemui/.SystemUIService config \
        > "$ONYX_STATE/systemui-services.txt" 2>&1 || return 1
    grep -Fq 'SERVICE com.android.systemui/.SystemUIService' "$ONYX_STATE/systemui-services.txt" \
        && grep -Eq '^[[:space:]]*Client:' "$ONYX_STATE/systemui-services.txt" \
        && grep -Eq '^[[:space:]]*Dump starting: ' "$ONYX_STATE/systemui-services.txt" \
        && grep -Eq '^[[:space:]]*Dump took [0-9]+ms$' "$ONYX_STATE/systemui-services.txt" || return 1
    ! grep -Eq '^[[:space:]]*(Failure while dumping the service:|Got a RemoteException while dumping the service|Error dumping service info|No services match)|\(not running\)' \
        "$ONYX_STATE/systemui-services.txt"
}
onyx_build_matches() {
    [ -f "$ONYX_MOD/compatibility.prop" ] || return 1
    . "$ONYX_MOD/compatibility.prop"
    [ "${ONYX_DEVICE:-}" = onyx ] && [ -n "${ONYX_INCREMENTAL:-}" ] || return 1
    [ "$(getprop ro.product.device)" = "$ONYX_DEVICE" ] || return 1
    [ "$(getprop ro.build.version.incremental)" = "$ONYX_INCREMENTAL" ] || return 1
    [ "$(getprop ro.build.version.sdk)" = "${ONYX_SDK:-37}" ] || return 1
}
onyx_check_visible() {
    onyx_manifest_format "$1" && (cd / && sha256sum -c "$1")
}
onyx_check_assets() {
    [ -s "$ONYX_MOD/assets.sha256" ] || return 1
    (cd "$ONYX_MOD" && sha256sum -c assets.sha256)
}
onyx_find_payload_root() {
    payload_root=$ONYX_MOD
    image_root=/data/adb/metamodule/mnt/$ONYX_ID
    [ ! -d "$image_root/system" ] || payload_root=$image_root
}
onyx_check_payload_layout() (
    payload_root=$1
    set --
    for partition in system vendor system_ext product odm oem; do
        if [ -e "$payload_root/$partition" ] || [ -L "$payload_root/$partition" ]; then
            set -- "$@" "$payload_root/$partition"
        fi
    done
    [ "$#" -gt 0 ] || return 1
    files=$(find -L "$@" ! -type d) || return 1
    printf '%s\n' "$files" | while IFS= read -r file; do
        [ -f "$file" ] || return 1
        relative=${file#"$payload_root/"}
        # KernelSU normalizes separate partitions into roots and nested symlinks.
        case "$relative" in
            system/vendor/*) relative=${relative#system/};;
            system_ext/*) relative=system/$relative;;
        esac
        case "$relative" in
            system/framework/services.jar \
                |vendor/etc/displayconfig/display_id_4630947173316895379.xml \
                |vendor/etc/displayconfig/display_id_4630947258895476883.xml) :;;
            "$ONYX_SYSTEMUI_ARCHIVE") onyx_has_systemui || return 1;;
            *) return 1;;
        esac
        # A normalized alias must identify the archive file, not another payload.
        [ "$file" -ef "$payload_root/$relative" ] || return 1
    done
)
onyx_check_archive_root() {
    onyx_manifest_contract || return 1
    onyx_check_payload_layout "$1" || return 1
    (cd "$1" && sha256sum -c "$ONYX_MOD/archive-payload.sha256")
}
onyx_check_archive() {
    onyx_find_payload_root
    onyx_check_archive_root "$payload_root"
}
onyx_label_payload_root() (
    payload_root=$1
    for relative in system system/framework vendor vendor/etc vendor/etc/displayconfig \
            system/framework/services.jar \
            vendor/etc/displayconfig/display_id_4630947173316895379.xml \
            vendor/etc/displayconfig/display_id_4630947258895476883.xml; do
        [ -e "$payload_root/$relative" ] || return 1
        "$ONYX_BUSYBOX" chcon --reference="/$relative" "$payload_root/$relative" || return 1
    done
    if onyx_has_systemui; then
        for relative in system/system_ext system/system_ext/priv-app \
                system/system_ext/priv-app/SystemUIGoogle "$ONYX_SYSTEMUI_ARCHIVE"; do
            [ -e "$payload_root/$relative" ] || return 1
            "$ONYX_BUSYBOX" chcon --reference="/${relative#system/}" \
                "$payload_root/$relative" || return 1
        done
    fi
)
onyx_label_payload() {
    onyx_find_payload_root
    onyx_label_payload_root "$payload_root"
}
onyx_check_watchdog() {
    cmp "$ONYX_MOD/common.sh" "$ONYX_STATE/common.sh" \
        && cmp "$ONYX_MOD/guard-service.sh" "$ONYX_STATE/guard-service.sh"
}
onyx_reject_before_mount() {
    printf '%s\n' "$*" > "$ONYX_STATE/failure"
    touch "$ONYX_MOD/disable"
    sync
    echo "$*"
    exit 0
}
onyx_fail_after_mount() {
    printf '%s\n' "$*" > "$ONYX_STATE/failure"
    touch "$ONYX_MOD/disable"
    rm -f "$ONYX_STATE/accepted"
    sync
    echo "$*"
    "$ONYX_REBOOT"
    exit 1
}
