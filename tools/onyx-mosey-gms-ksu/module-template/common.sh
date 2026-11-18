#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
MOSEY_MOD=${0%/*}
MOSEY_STATE=/data/adb/onyx-mosey-gms
MOSEY_CE=/data/user/0/com.google.android.gms/databases/phenotype.db
MOSEY_DE=/data/user_de/0/com.google.android.gms/databases/phenotype.db
MOSEY_BINDER=com.google.android.moseyservice.IMoseyService/default
MOSEY_GMS_VERSION=264630035
MOSEY_APP_VERSION=60715
MOSEY_STORAGE_INFO=/data/user/0/com.google.android.mosey/files/phenotype_storage_info/shared/storage-info.pb

mosey_framework() {
    mosey_tool=$1; shift
    case "$mosey_tool" in
        timeout)
            mosey_seconds=$1; shift
            mosey_tool=$1; shift
            case "$mosey_tool" in am|cmd|dumpsys|pm|service|getprop) :;; *) return 2;; esac
            /system/bin/timeout "$mosey_seconds" "/system/bin/$mosey_tool" "$@";;
        am|cmd|dumpsys|pm|service|getprop) "/system/bin/$mosey_tool" "$@";;
        *) return 2;;
    esac
}
mosey_log() {
    printf '%s\n' "$*"
    printf '%s\n' "$*" >> "$MOSEY_STATE/status.log"
    /system/bin/log -t MoseyOnyx "$*" 2>/dev/null || :
}
mosey_init() {
    umask 077
    [ "$(id -u)" = 0 ] || return 1
    mkdir -p "$MOSEY_STATE" || return 1
    MOSEY_SQLITE=$(command -v sqlite3) || return 1
}
mosey_device_matches() {
    [ "$(mosey_framework getprop ro.product.device)" = onyx ] || return 1
    [ "$(mosey_framework getprop ro.build.version.sdk)" = 37 ]
}
mosey_user_unlocked() {
    mosey_user_state=$(mosey_framework timeout 3 cmd activity get-started-user-state 0 2>/dev/null) || return 1
    [ "$mosey_user_state" = RUNNING_UNLOCKED ]
}
mosey_active_package_version() {
    # Updated system apps also dump an older APK under Hidden system packages.
    awk -v package="$1" '
      /^[[:space:]]*Packages:/ { packages=1; active=0; next }
      /^[[:space:]]*Hidden system packages:/ { packages=0; active=0; next }
      packages && /^[[:space:]]*Package \[/ {
        active=index($0,"Package [" package "] ")>0; next
      }
      active && /^[[:space:]]*versionCode=[0-9]/ {
        line=$0
        sub(/^[[:space:]]*versionCode=/,"",line)
        sub(/[^0-9].*$/,"",line)
        version=line; count++
      }
      END { if (count!=1) exit 1; print version }
    '
}
mosey_active_gms_version() {
    mosey_active_package_version com.google.android.gms
}
mosey_app_compatible() {
    mosey_app_version=$(mosey_framework timeout 5 dumpsys package com.google.android.mosey 2>/dev/null \
        | mosey_active_package_version com.google.android.mosey) || return 1
    [ "$mosey_app_version" = "$MOSEY_APP_VERSION" ]
}
mosey_compatible() {
    mosey_device_matches || return 1
    mosey_version=$(mosey_framework timeout 5 dumpsys package com.google.android.gms 2>/dev/null \
        | mosey_active_gms_version) || return 1
    [ "$mosey_version" = "$MOSEY_GMS_VERSION" ]
}
mosey_policy_apply() {
    [ -x "$MOSEY_MOD/bin/onyx-mosey-nlmsg" ] || return 1
    /system/bin/timeout 20 "$MOSEY_MOD/bin/onyx-mosey-nlmsg" --apply > "$MOSEY_STATE/policy.log" 2>&1 || return 1
}
mosey_cache() {
    case "$1" in --apply|--inspect|--rollback|--release-country) :;; *) return 2;; esac
    [ -x "$MOSEY_MOD/bin/onyx-mosey-cache" ] || return 1
    /system/bin/timeout 20 "$MOSEY_MOD/bin/onyx-mosey-cache" "$1" \
        --storage-info "$MOSEY_STORAGE_INFO" --state-dir "$MOSEY_STATE"
}
mosey_inspect() {
    [ -f "$1" ] || return 1
    case "${2:-ce}" in
        de) mosey_sql=inspect-de.sql;; ce) mosey_sql=inspect.sql;;
        de-mosey) mosey_sql=inspect-mosey-de.sql;; ce-mosey) mosey_sql=inspect-mosey.sql;;
        *) return 1;;
    esac
    mosey_sql_text "$mosey_sql" "${2:-ce}" | "$MOSEY_SQLITE" -bail -readonly -cmd '.timeout 1000' "$1"
}
mosey_sql_text() {
    case "$2" in ce-mosey|de-mosey) cat "$MOSEY_MOD/mosey-flags.sql" || return 1;; esac
    cat "$MOSEY_MOD/$1"
}
mosey_release_country() {
    mosey_country_db=$1; mosey_country_label=$2
    case "$mosey_country_label" in
        ce-mosey) mosey_country_sql=release-country.sql;;
        de-mosey) mosey_country_sql=release-country-de.sql;;
        *) return 2;;
    esac
    mosey_country_baseline="$MOSEY_STATE/$mosey_country_label-before.sqlite"
    mosey_country_marker="$MOSEY_STATE/$mosey_country_label-country-released"
    if [ ! -f "$mosey_country_baseline" ]; then
        # Fresh installs own no country entry. Partial legacy state is unsafe.
        [ ! -e "$mosey_country_baseline" ] && [ ! -e "$mosey_country_marker" ] &&
        [ ! -e "$MOSEY_STATE/$mosey_country_label-version" ] &&
        [ ! -e "$MOSEY_STATE/$mosey_country_label-app-version" ] || return 1
        printf '%s\n' unchanged
        return 0
    fi
    [ ! -L "$mosey_country_baseline" ] && [ -f "$mosey_country_db" ] || return 1
    [ "$(cat "$MOSEY_STATE/$mosey_country_label-version")" = "$MOSEY_GMS_VERSION" ] || return 1
    [ "$(cat "$MOSEY_STATE/$mosey_country_label-app-version")" = "$MOSEY_APP_VERSION" ] || return 1
    mosey_country_hash=$(sha256sum "$mosey_country_baseline") || return 1
    mosey_country_hash=${mosey_country_hash%% *}
    if [ -f "$mosey_country_marker" ]; then
        [ ! -L "$mosey_country_marker" ] &&
        [ "$(cat "$mosey_country_marker")" = "$mosey_country_hash" ] || return 1
        # Once released, future genuine country updates belong to GMS.
        printf '%s\n' unchanged
        return 0
    fi
    [ ! -e "$mosey_country_marker" ] || return 1
    mosey_country_result=$({
        printf "ATTACH DATABASE 'file:%s?mode=ro' AS baseline;\n" "$mosey_country_baseline"
        mosey_sql_text "$mosey_country_sql" "$mosey_country_label"
    } | "$MOSEY_SQLITE" -bail -cmd '.timeout 5000' "$mosey_country_db") || return 1
    case "$mosey_country_result" in changed|unchanged) :;; *) return 1;; esac
    mosey_country_verify=$(sha256sum "$mosey_country_baseline") || return 1
    [ "${mosey_country_verify%% *}" = "$mosey_country_hash" ] || return 1
    printf '%s\n' "$mosey_country_hash" > "$mosey_country_marker.tmp" &&
        mv "$mosey_country_marker.tmp" "$mosey_country_marker" || return 1
    printf '%s\n' "$mosey_country_result"
}
mosey_apply_database() {
    mosey_db=$1; mosey_label=$2
    case "$mosey_label" in
        de) mosey_apply_sql=apply-de.sql;; ce) mosey_apply_sql=apply.sql;;
        de-mosey) mosey_apply_sql=apply-mosey-de.sql;; ce-mosey) mosey_apply_sql=apply-mosey.sql;;
        *) return 1;;
    esac
    mosey_release_result=unchanged
    case "$mosey_label" in ce-mosey|de-mosey)
        mosey_release_result=$(mosey_release_country "$mosey_db" "$mosey_label") || return 1;;
    esac
    mosey_before=$(mosey_inspect "$mosey_db" "$mosey_label") || return 1
    case "$mosey_before" in
        true) printf '%s\n' "$mosey_release_result"; return 0;;
        absent|false|unlinked) :;;
        *) mosey_log "$mosey_label skipped: $mosey_before" >&2; return 1;;
    esac
    # SQLite backs up the live WAL coherently. Never copy/remove WAL/SHM files.
    # Additional flags use their own baseline: an older module's Nearby backup
    # must not become the rollback source for later app flag changes.
    mosey_backup_prefix=$mosey_label
    case "$mosey_label" in ce-mosey|de-mosey) mosey_backup_prefix="$mosey_label-bool-v10";; esac
    mosey_backup="$MOSEY_STATE/$mosey_backup_prefix-before.sqlite"
    case "$mosey_label" in ce-mosey|de-mosey)
        if [ -f "$mosey_backup" ]; then
            [ "$(cat "$MOSEY_STATE/$mosey_backup_prefix-version")" = "$MOSEY_GMS_VERSION" ] || return 1
            [ "$(cat "$MOSEY_STATE/$mosey_backup_prefix-app-version")" = "$MOSEY_APP_VERSION" ] || return 1
        fi;;
    esac
    if [ ! -f "$mosey_backup" ]; then
        "$MOSEY_SQLITE" -bail -readonly -cmd '.timeout 1000' "$mosey_db" \
            ".backup '$mosey_backup.tmp'" || return 1
        [ "$("$MOSEY_SQLITE" -bail -readonly "$mosey_backup.tmp" 'PRAGMA quick_check;')" = ok ] || return 1
        mv "$mosey_backup.tmp" "$mosey_backup" || return 1
        printf '%s\n' "$MOSEY_GMS_VERSION" > "$MOSEY_STATE/$mosey_backup_prefix-version" || return 1
        case "$mosey_label" in ce-mosey|de-mosey)
            printf '%s\n' "$MOSEY_APP_VERSION" > "$MOSEY_STATE/$mosey_backup_prefix-app-version" || return 1;;
        esac
    fi
    mosey_result=$(mosey_sql_text "$mosey_apply_sql" "$mosey_label" \
        | "$MOSEY_SQLITE" -bail -cmd '.timeout 5000' "$mosey_db") || return 1
    [ "$(mosey_inspect "$mosey_db" "$mosey_label")" = true ] || return 1
    case "$mosey_result" in changed|unchanged) :;; *) return 1;; esac
    if [ "$mosey_release_result" = changed ]; then mosey_result=changed; fi
    printf '%s\n' "$mosey_result"
}
mosey_pid_live() {
    case "$1" in ''|0|*[!0-9]*) return 1;; esac
    [ -r "/proc/$1/stat" ] || return 1
    mosey_stat=$(cat "/proc/$1/stat") || return 1
    mosey_proc_fields=${mosey_stat##*) }
    case "${mosey_proc_fields%% *}" in Z|X) return 1;; esac
}
mosey_parse_services() {
    # Check each ServiceRecord separately; another service's ProcessRecord
    # must not make an unstarted provider/delegate look ready.
    awk '
      function finish() {
        if (kind==1 && pid>0) provider=pid
        if (kind==2 && pid>0 && foreground && delegate) delegated=pid
      }
      /^[[:space:]]*\* ServiceRecord\{/ {
        finish(); kind=0; pid=0; foreground=0; delegate=0
        if ($0 ~ / u0 com\.google\.android\.mosey\/(\.ExternalSharingService|com\.google\.android\.mosey\.ExternalSharingService)[[:space:]}]/) kind=1
        if ($0 ~ / u0 com\.google\.android\.mosey\/SPECIAL_USE:FgsDelegate[[:space:]}]/) kind=2
        next
      }
      kind && /^[[:space:]]*app=ProcessRecord\{/ {
        line=$0
        sub(/^.*ProcessRecord\{[^[:space:]]+[[:space:]]+/,"",line)
        if (line ~ /^[1-9][0-9]*:com\.google\.android\.mosey\//) {
          sub(/:.*$/,"",line); pid=line
        }
      }
      kind==2 && /^[[:space:]]*isForeground=true([[:space:]]|$)/ { foreground=1 }
      kind==2 && /^[[:space:]]*isFgsDelegate=true([[:space:]]|$)/ { delegate=1 }
      END { finish(); printf "%d:%d\n",provider,delegated }
    '
}
mosey_provider_start() {
    [ "$(mosey_inspect "$MOSEY_CE")" = true ] || return 1
    mosey_binder_attempt=0
    while :; do
        mosey_binder_state=$(mosey_framework timeout 2 service check "$MOSEY_BINDER" 2>/dev/null) || mosey_binder_state=
        case "$mosey_binder_state" in *': found'*) break;; esac
        mosey_binder_attempt=$((mosey_binder_attempt+1))
        [ "$mosey_binder_attempt" -lt 15 ] || return 1
        sleep 1
    done
    mosey_packages=$(mosey_framework pm list packages -e --user 0 com.google.android.mosey) || return 1
    [ "$mosey_packages" = package:com.google.android.mosey ] || return 1
    # The APK boot receiver may have disabled this component before Binder
    # registration. Preserve a user-disabled package; restore only the component.
    mosey_framework pm enable --user 0 com.google.android.mosey/.ExternalSharingService >/dev/null || return 1
    mosey_framework cmd deviceidle tempwhitelist -d 30000 com.google.android.mosey >/dev/null || return 1
    mosey_start=$(mosey_framework am startservice --user 0 -n com.google.android.mosey/.ExternalSharingService 2>&1) || return 1
    case "$mosey_start" in *Error*|*Exception*) mosey_log "$mosey_start"; return 1;; esac
    mosey_provider_attempt=0; mosey_delegate_requested=0
    while [ "$mosey_provider_attempt" -lt 15 ]; do
        mosey_records=$(mosey_framework timeout 3 dumpsys activity services com.google.android.mosey) || return 1
        mosey_pids=$(printf '%s\n' "$mosey_records" | mosey_parse_services) || return 1
        # A literal | is alternation in Android mksh parameter patterns.
        mosey_provider_pid=${mosey_pids%%:*}; mosey_delegate_pid=${mosey_pids#*:}
        if mosey_pid_live "$mosey_provider_pid"; then
            if [ "$mosey_delegate_pid" = "$mosey_provider_pid" ] && mosey_pid_live "$mosey_delegate_pid"; then
                mosey_log "Mosey provider ready: pid=$mosey_provider_pid; foreground-service delegate verified."
                return 0
            fi
            if [ "$mosey_delegate_requested" = 0 ]; then
                mosey_framework cmd activity set-foreground-service-delegate --user 0 com.google.android.mosey start || return 1
                mosey_delegate_requested=1
            fi
        fi
        mosey_provider_attempt=$((mosey_provider_attempt+1))
        sleep 1
    done
    return 1
}
