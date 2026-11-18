#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
WDR_STATE=/data/adb/onyx-wonder-driver
WDR_SYS=/sys
WDR_PROC=/proc
WDR_VENDOR=/vendor_dlkm/lib/modules
WDR_NAME=qca_cld3_wcn7750
WDR_STAGE=early
WDR_RELEASE=6.18.63-android17-6-maybe-dirty-4k
WDR_STOCK_SHA=0a2eba04b57ccdc0ae9e57258b91b38440e4b983fa9e151fe5acf36a3d915969
WDR_OPTIONS='options qca_cld3_wcn7750 sta_monitor_coexist=1 ap_monitor_coexist=1 sta_ap_monitor_coexist=1 wonder_enabled=1'

wdr_android() {
    wdr_tool=$1; shift
    case "$wdr_tool" in
        getprop|uname|id|sha256sum|rmmod|insmod|log|tr|chcon)
            "/system/bin/$wdr_tool" "$@";;
        *) return 2;;
    esac
}
wdr_log() {
    printf '%s\n' "$*"
    printf '%s\n' "$*" >> "$WDR_STATE/status.log"
    wdr_android log -t WonderDriverOnyx "$*" 2>/dev/null || :
}
wdr_sha() {
    wdr_sha_line=$(wdr_android sha256sum "$1" 2>/dev/null) || return 1
    printf '%s\n' "${wdr_sha_line%% *}"
}
wdr_init() {
    umask 077
    [ "$(wdr_android id -u)" = 0 ] || return 1
    [ ! -e "$WDR_MOD/disable" ] && [ ! -e "$WDR_MOD/remove" ] || return 1
    mkdir -p "$WDR_STATE" || return 1
    [ -r "$WDR_MOD/payload-contract.sh" ] || return 1
    . "$WDR_MOD/payload-contract.sh"
}
wdr_device_matches() {
    [ "$(wdr_android getprop ro.product.device)" = onyx ] || return 1
    [ "$(wdr_android getprop ro.build.version.sdk)" = 37 ] || return 1
    [ "$(wdr_android uname -r)" = "$WDR_RELEASE" ]
}
wdr_payload_matches() {
    [ -r "$WDR_MOD/payload-contract.sh" ] || return 1
    . "$WDR_MOD/payload-contract.sh"
    case "$WDR_REPLACEMENT_SHA" in ''|*[!0-9a-f]*) return 1;; esac
    [ "${#WDR_REPLACEMENT_SHA}" = 64 ] || return 1
    [ "$(wdr_sha "$WDR_MOD/payload/$WDR_NAME.ko")" = "$WDR_REPLACEMENT_SHA" ]
}
wdr_stock_matches() {
    [ "$(wdr_sha "$WDR_VENDOR/$WDR_NAME.ko")" = "$WDR_STOCK_SHA" ] || return 1
    # Reject a conflicting second path rather than assume a partition alias.
    if [ -e "/vendor/lib/modules/$WDR_NAME.ko" ]; then
        [ "$(wdr_sha "/vendor/lib/modules/$WDR_NAME.ko")" = "$WDR_STOCK_SHA" ] || return 1
    fi
}
wdr_options_match() {
    [ -r "$WDR_VENDOR/modules.options" ] || return 1
    wdr_options=$(awk '
      { sub(/#.*/, "") }
      $1=="options" && $2=="qca_cld3_wcn7750" {
        n++; line=$1; for (i=2;i<=NF;i++) line=line " " $i
      }
      END { if (n!=1) exit 1; print line }
    ' "$WDR_VENDOR/modules.options") || return 1
    [ "$wdr_options" = "$WDR_OPTIONS" ] || return 1
    # These are the four reviewed ordinary bool init args, not arbitrary callbacks.
    for wdr_parameter in sta_monitor_coexist ap_monitor_coexist sta_ap_monitor_coexist wonder_enabled; do
        wdr_value=$(cat "$WDR_SYS/module/$WDR_NAME/parameters/$wdr_parameter" 2>/dev/null) || return 1
        case "$wdr_value" in Y|1) :;; *) return 1;; esac
    done
}
wdr_early_quiet() {
    [ "$(wdr_android getprop vendor.all.modules.ready)" = 1 ] || return 1
    [ "$(wdr_android getprop init.svc.vendor.modprobe)" = stopped ] || return 1
    case "$(wdr_android getprop init.svc.zygote)" in ''|stopped) :;; *) return 1;; esac
    case "$(wdr_android getprop sys.boot_completed)" in ''|0) :;; *) return 1;; esac
    for wdr_comm in "$WDR_PROC"/[0-9]*/comm; do
        [ -r "$wdr_comm" ] || continue
        wdr_comm_value=$(cat "$wdr_comm" 2>/dev/null) || return 1
        case "$wdr_comm_value" in zygote|zygote32|zygote64) return 1;; esac
    done
    wdr_native_interfaces_quiet
}
wdr_live_quiet() {
    [ "$(wdr_android getprop vendor.all.modules.ready)" = 1 ] || return 1
    [ "$(wdr_android getprop init.svc.vendor.modprobe)" = stopped ] || return 1
    # The caller stops provider/native/Wi-Fi first. Never stop zygote here.
    wdr_native_interfaces_quiet
}
wdr_native_interfaces_quiet() {
    for wdr_service in mosey_server vendor.wifi_hal_legacy wpa_supplicant hostapd; do
        case "$(wdr_android getprop "init.svc.$wdr_service")" in ''|stopped) :;; *) return 1;; esac
    done
    # No APK provider or native/helper process may own the radio.
    for wdr_cmdline in "$WDR_PROC"/[0-9]*/cmdline; do
        [ -r "$wdr_cmdline" ] || continue
        wdr_process=$(wdr_android tr '\000' '\n' < "$wdr_cmdline" 2>/dev/null) || return 1
        case "$wdr_process" in
            *com.google.android.mosey*|*mosey_server*|*onyx_mosey_launcher*|*android.hardware.wifi-service*|*wpa_supplicant*|*hostapd*) return 1;;
        esac
    done
    for wdr_interface in "$WDR_SYS"/class/net/*; do
        [ -d "$wdr_interface" ] || continue
        wdr_ifname=${wdr_interface##*/}
        case "$wdr_ifname" in wlan*|p2p*|wonder*|mon*) :;;
            *) [ -e "$wdr_interface/phy80211" ] || [ -d "$wdr_interface/wireless" ] || continue;;
        esac
        wdr_flags=$(cat "$wdr_interface/flags" 2>/dev/null) || return 1
        case "$wdr_flags" in 0x?*) :;; *) return 1;; esac
        case "${wdr_flags#0x}" in *[!0-9a-fA-F]*) return 1;; esac
        [ "$((wdr_flags & 1))" = 0 ] || return 1
    done
    # Coexistence sessions own module refs. Also explicitly reject a visible session.
    [ "$(cat "$WDR_SYS/module/$WDR_NAME/parameters/wonder_coex_stats" 2>/dev/null)" = active=0 ]
}
wdr_unloadable() {
    [ "$(cat "$WDR_SYS/module/$WDR_NAME/initstate" 2>/dev/null)" = live ] || return 1
    [ "$(cat "$WDR_SYS/module/$WDR_NAME/refcnt" 2>/dev/null)" = 0 ] || return 1
    [ -d "$WDR_SYS/module/$WDR_NAME/holders" ] || return 1
    for wdr_holder in "$WDR_SYS/module/$WDR_NAME/holders/"*; do
        [ ! -e "$wdr_holder" ] || return 1
    done
    awk -v name="$WDR_NAME" '$1==name { n++; if ($3!=0 || $4!="-" || $5!="Live") bad=1 }
      END { exit (n!=1 || bad) }' "$WDR_PROC/modules" || return 1
    # If the running module exposes its build note, require the stock note too.
    wdr_note="$WDR_SYS/module/$WDR_NAME/notes/.note.gnu.build-id"
    if [ -r "$wdr_note" ]; then
        [ "$(wdr_sha "$wdr_note")" = "$WDR_STOCK_NOTE_SHA" ] || return 1
    fi
}
wdr_preflight() {
    wdr_device_matches || { wdr_log 'Skipped: device or kernel differs.'; return 1; }
    wdr_payload_matches || { wdr_log 'Skipped: replacement SHA differs.'; return 1; }
    wdr_stock_matches || { wdr_log 'Skipped: stock module SHA differs.'; return 1; }
    wdr_options_match || { wdr_log 'Skipped: stock options or init booleans differ.'; return 1; }
    case "$WDR_STAGE" in
        early) wdr_early_quiet;; live) wdr_live_quiet;; *) return 1;;
    esac || { wdr_log 'Skipped: vendor/native/provider/interface guards failed.'; return 1; }
    wdr_unloadable || { wdr_log 'Skipped: QCA is not live, idle and unreferenced.'; return 1; }
}
wdr_replacement_running() {
    [ "$(cat "$WDR_SYS/module/$WDR_NAME/initstate" 2>/dev/null)" = live ] || return 1
    [ "$(cat "$WDR_SYS/module/$WDR_NAME/parameters/wonder_lifecycle_revision" 2>/dev/null)" = 1 ] || return 1
    [ "$(wdr_sha "$WDR_SYS/module/$WDR_NAME/notes/.note.gnu.build-id")" = "$WDR_REPLACEMENT_NOTE_SHA" ]
}
wdr_insmod() {
    # Fixed reviewed options match the vendor loader exactly. No eval or rmmod -f.
    wdr_android insmod "$1" sta_monitor_coexist=1 ap_monitor_coexist=1 \
        sta_ap_monitor_coexist=1 wonder_enabled=1
}
wdr_reload() (
    mkdir "$WDR_STATE/reload.lock" 2>/dev/null || { wdr_log 'Skipped: another reload holds the lock.'; exit 1; }
    trap 'rmdir "$WDR_STATE/reload.lock" 2>/dev/null || :' EXIT
    wdr_boot=$(cat "$WDR_PROC/sys/kernel/random/boot_id" 2>/dev/null) || exit 1
    case "$wdr_boot" in ''|*[!0-9a-f-]*) exit 1;; esac
    wdr_attempt="$WDR_STATE/$wdr_boot"
    [ ! -e "$wdr_attempt" ] || { wdr_log 'Skipped: this boot already attempted replacement.'; exit 1; }
    wdr_preflight || exit 1
    mkdir "$wdr_attempt" || exit 1
    cp "$WDR_VENDOR/$WDR_NAME.ko" "$wdr_attempt/stock.ko" || exit 1
    [ "$(wdr_sha "$wdr_attempt/stock.ko")" = "$WDR_STOCK_SHA" ] || exit 1
    # Label both files before unload so policy rejection cannot strand the radio.
    wdr_android chcon u:object_r:vendor_file:s0 "$wdr_attempt/stock.ko" || exit 1
    wdr_android chcon u:object_r:vendor_file:s0 "$WDR_MOD/payload/$WDR_NAME.ko" || exit 1
    cp "$WDR_VENDOR/modules.options" "$wdr_attempt/modules.options" || exit 1
    printf '%s\n' "$WDR_OPTIONS" > "$wdr_attempt/init-options"
    for wdr_parameter in sta_monitor_coexist ap_monitor_coexist sta_ap_monitor_coexist wonder_enabled; do
        cat "$WDR_SYS/module/$WDR_NAME/parameters/$wdr_parameter" > "$wdr_attempt/$wdr_parameter" || exit 1
    done
    # Recheck immediately before the only destructive operation.
    wdr_preflight || exit 1
    wdr_log 'Reloading reviewed QCA module with normal unload; all dependency modules stay loaded.'
    if ! wdr_android rmmod "$WDR_NAME" > "$wdr_attempt/rmmod.log" 2>&1; then
        wdr_log 'Normal QCA unload rejected; replacement was not loaded.'
        exit 1
    fi
    if [ -d "$WDR_SYS/module/$WDR_NAME" ]; then
        wdr_log 'QCA still appears loaded; replacement skipped and future boot hook disabled.'
        touch "$WDR_MOD/disable"
        exit 1
    fi
    if wdr_insmod "$WDR_MOD/payload/$WDR_NAME.ko" > "$wdr_attempt/insmod.log" 2>&1; then
        if wdr_replacement_running; then
            printf '%s\n' "$WDR_REPLACEMENT_SHA" > "$wdr_attempt/replacement-loaded"
            wdr_log 'Reviewed QCA replacement loaded. Disable and reboot to restore vendor stock.'
            exit 0
        fi
        wdr_log 'Replacement insertion did not prove the reviewed running build/revision; hook disabled.'
        touch "$WDR_MOD/disable"
        exit 1
    fi
    # A rejected insertion should leave no module. Never force removal of leftovers.
    touch "$WDR_MOD/disable"
    if [ -d "$WDR_SYS/module/$WDR_NAME" ]; then
        wdr_log 'Replacement rejected but QCA still exists; automatic rollback skipped.'
        exit 1
    fi
    [ "$(wdr_sha "$wdr_attempt/stock.ko")" = "$WDR_STOCK_SHA" ] || exit 1
    if wdr_insmod "$wdr_attempt/stock.ko" > "$wdr_attempt/rollback-insmod.log" 2>&1 \
        && [ "$(cat "$WDR_SYS/module/$WDR_NAME/initstate" 2>/dev/null)" = live ]; then
        touch "$wdr_attempt/stock-restored"
        wdr_log 'Replacement rejected; original QCA restored with the same init options. Hook disabled.'
    else
        wdr_log 'Replacement and stock rollback insertion failed. Hook disabled; reboot loads vendor stock.'
    fi
    exit 1
)
