#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
. "${0%/*}/common.sh"
mosey_init || exit 0
while [ "$(mosey_framework getprop sys.boot_completed)" != 1 ] || ! mosey_user_unlocked; do
    [ ! -e "$MOSEY_MOD/disable" ] && [ ! -e "$MOSEY_MOD/remove" ] || exit 0
    sleep 5
done
mosey_compatible || { mosey_log 'Unsupported device/GMS version; no database changed.'; exit 0; }
mosey_app_compatible || { mosey_log 'Unsupported Mosey APK flag contract; startup skipped.'; exit 0; }
mosey_policy_apply || { mosey_log 'Native policy update rejected; startup skipped. See policy.log.'; exit 0; }
# Registration can arrive shortly after the first unlock on a fresh GMS install.
mosey_attempt=0
while [ "$(mosey_inspect "$MOSEY_CE" 2>/dev/null)" = not-ready ] && [ "$mosey_attempt" -lt 30 ]; do
    [ ! -e "$MOSEY_MOD/disable" ] && [ ! -e "$MOSEY_MOD/remove" ] || exit 0
    mosey_attempt=$((mosey_attempt+1))
    sleep 2
done
# Some DE databases have no Nearby registration; that is an expected skip.
mosey_late_de=unchanged
mosey_de_state=$(mosey_inspect "$MOSEY_DE" de 2>/dev/null) || mosey_de_state=schema-mismatch
case "$mosey_de_state" in
    absent|false|unlinked) mosey_late_de=$(mosey_apply_database "$MOSEY_DE" de) || exit 0;;
    true|not-ready) :;;
    *) mosey_log "DE schema/value rejected: $mosey_de_state"; exit 0;;
esac
mosey_changed=$(mosey_apply_database "$MOSEY_CE" ce) || { mosey_log 'CE transaction rejected; provider startup skipped.'; exit 0; }
mosey_log "Late CE override: $mosey_changed"
mosey_attempt=0
while [ "$(mosey_inspect "$MOSEY_CE" ce-mosey 2>/dev/null)" = not-ready ] && [ "$mosey_attempt" -lt 30 ]; do
    [ ! -e "$MOSEY_MOD/disable" ] && [ ! -e "$MOSEY_MOD/remove" ] || exit 0
    mosey_attempt=$((mosey_attempt+1)); sleep 2
done
mosey_country_de=$(mosey_release_country "$MOSEY_DE" de-mosey) || { mosey_log 'Legacy Mosey DE country release rejected; startup skipped.'; exit 0; }
mosey_country_ce=$(mosey_release_country "$MOSEY_CE" ce-mosey) || { mosey_log 'Legacy Mosey CE country release rejected; startup skipped.'; exit 0; }
mosey_app_de=unchanged
mosey_app_de_state=$(mosey_inspect "$MOSEY_DE" de-mosey 2>/dev/null) || mosey_app_de_state=schema-mismatch
case "$mosey_app_de_state" in
    absent|false|unlinked) mosey_app_de=$(mosey_apply_database "$MOSEY_DE" de-mosey) || exit 0;;
    true|not-ready) :;;
    *) mosey_log "Mosey DE schema/value rejected: $mosey_app_de_state"; exit 0;;
esac
mosey_app_ce=$(mosey_apply_database "$MOSEY_CE" ce-mosey) || { mosey_log 'Mosey CE transaction rejected; startup skipped.'; exit 0; }
mosey_log "Mosey app flags: CE=$mosey_app_ce DE=$mosey_app_de"
mosey_app_changed=0
mosey_gms_restarted=0
if [ "$mosey_app_ce" = changed ] || [ "$mosey_app_de" = changed ] || \
   [ "$mosey_country_ce" = changed ] || [ "$mosey_country_de" = changed ]; then
    # The APK's own cached flag getters must reload as well as GMS's getters.
    mosey_framework am force-stop --user 0 com.google.android.mosey || exit 0
    mosey_app_changed=1
fi
if [ "$mosey_changed" = changed ] || [ "$mosey_late_de" = changed ] || \
   [ "$mosey_app_changed" = 1 ] || \
   [ "$(cat "$MOSEY_STATE/de-changed-boot" 2>/dev/null)" = "$(cat /proc/sys/kernel/random/boot_id)" ]; then
    # In-process GMS getters cache overrides; one restart after an actual change.
    mosey_boot_id=$(cat /proc/sys/kernel/random/boot_id)
    if [ "$mosey_app_changed" = 1 ] || \
       [ "$(cat "$MOSEY_STATE/gms-restarted-boot" 2>/dev/null)" != "$mosey_boot_id" ]; then
        mosey_framework am force-stop --user 0 com.google.android.gms || exit 0
        mosey_gms_restarted=1
        printf '%s\n' "$mosey_boot_id" > "$MOSEY_STATE/gms-restarted-boot"
    fi
fi
# GMS's shared primary cache takes precedence over the app's refreshed fallback.
# Release legacy country metadata before applying the hopping Boolean.
# Stop both publishers/consumers before the helper can replace a cache file.
if [ "$mosey_app_changed" != 1 ]; then
    mosey_framework am force-stop --user 0 com.google.android.mosey || exit 0
    mosey_app_changed=1
fi
if [ "$mosey_gms_restarted" != 1 ]; then
    mosey_framework am force-stop --user 0 com.google.android.gms || exit 0
    mosey_gms_restarted=1
fi
mosey_cache_country=$(mosey_cache --release-country) || { mosey_log 'Legacy shared-cache country release rejected; startup skipped.'; exit 0; }
case "$mosey_cache_country" in changed|unchanged) :;; *) mosey_log 'Invalid shared-cache country release result; startup skipped.'; exit 0;; esac
# Repair the Boolean override even when the SQL value is already correct.
mosey_cache_before=$(mosey_cache --inspect) || { mosey_log 'Shared cache inspection rejected; startup skipped.'; exit 0; }
case "$mosey_cache_before" in
    true) mosey_cache_changed=unchanged;;
    false)
        # Stop both cache consumers and the GMS publisher before replacing its file.
        # The helper also rechecks file identity immediately before publication.
        if [ "$mosey_app_changed" != 1 ]; then
            mosey_framework am force-stop --user 0 com.google.android.mosey || exit 0
            mosey_app_changed=1
        fi
        if [ "$mosey_gms_restarted" != 1 ]; then
            mosey_framework am force-stop --user 0 com.google.android.gms || exit 0
        fi
        mosey_cache_changed=$(mosey_cache --apply) || { mosey_log 'Shared cache update rejected; startup skipped.'; exit 0; };;
    *) mosey_log 'Invalid shared cache inspection; startup skipped.'; exit 0;;
esac
case "$mosey_cache_changed" in changed|unchanged) :;; *) mosey_log 'Invalid shared cache helper result; startup skipped.'; exit 0;; esac
[ "$(mosey_cache --inspect)" = true ] || { mosey_log 'Shared cache verification failed; startup skipped.'; exit 0; }
mosey_log "Mosey shared cache: $mosey_cache_changed"
mosey_provider_start || mosey_log 'Provider startup failed; inspect native Binder/service logs.'
