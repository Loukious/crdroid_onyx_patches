#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
. "${0%/*}/common.sh"
mosey_init && mosey_compatible || exit 1
mosey_app_compatible || exit 1
mosey_user_unlocked || exit 1
touch "$MOSEY_MOD/disable" || exit 1
mosey_framework cmd activity set-foreground-service-delegate --user 0 com.google.android.mosey stop || :
mosey_framework am stopservice --user 0 -n com.google.android.mosey/.ExternalSharingService || :
mosey_framework am force-stop --user 0 com.google.android.mosey || exit 1
mosey_framework am force-stop --user 0 com.google.android.gms || exit 1
mosey_restored=0
for mosey_label in de-mosey ce-mosey de ce; do
    case "$mosey_label" in de|de-mosey) mosey_db=$MOSEY_DE;; ce|ce-mosey) mosey_db=$MOSEY_CE;; esac
    mosey_backup_prefix=$mosey_label
    case "$mosey_label" in ce-mosey|de-mosey)
        mosey_backup_prefix="$mosey_label-bool-v10";;
    esac
    mosey_backup="$MOSEY_STATE/$mosey_backup_prefix-before.sqlite"
    [ -f "$mosey_backup" ] || continue
    [ "$(cat "$MOSEY_STATE/$mosey_backup_prefix-version")" = "$MOSEY_GMS_VERSION" ] || exit 1
    case "$mosey_label" in de-mosey|ce-mosey)
        [ "$(cat "$MOSEY_STATE/$mosey_backup_prefix-app-version")" = "$MOSEY_APP_VERSION" ] || exit 1;;
    esac
    [ "$(mosey_inspect "$mosey_db" "$mosey_label")" = true ] || exit 1
    case "$mosey_label" in
        de) mosey_rollback_sql=rollback-de.sql;; ce) mosey_rollback_sql=rollback.sql;;
        de-mosey) mosey_rollback_sql=rollback-mosey-de.sql;; ce-mosey) mosey_rollback_sql=rollback-mosey.sql;;
    esac
    { printf "ATTACH DATABASE 'file:%s?mode=ro' AS baseline;\n" "$mosey_backup";
      mosey_sql_text "$mosey_rollback_sql" "$mosey_label"; } | "$MOSEY_SQLITE" -bail -cmd '.timeout 5000' "$mosey_db" || exit 1
    mosey_restored=1
done
mosey_cache_restored=$(mosey_cache --rollback) || { mosey_log 'Shared cache rollback rejected; inspect the retained private baseline.'; exit 1; }
case "$mosey_cache_restored" in
    changed) mosey_restored=1;;
    unchanged) :;;
    *) mosey_log 'Invalid shared cache rollback result.'; exit 1;;
esac
mosey_log 'Rollback complete. Scoped database and shared-cache flag overrides restored; module disabled.'
