#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
ONYX_MOD=$MODPATH
. "$MODPATH/common.sh"
[ "${KSU:-}" = true ] || abort '! This test requires KernelSU Next'
onyx_build_matches || abort '! This ZIP targets a different Onyx ROM'
onyx_manifest_contract || abort '! Installed and archive payload manifests differ'
onyx_check_visible "$MODPATH/baseline.sha256" || abort '! Installed base artifacts differ'
onyx_check_assets || abort '! Module metadata or scripts are damaged'
# At installation the archive is still under MODPATH, before MetaModule relocation.
onyx_check_archive_root "$MODPATH" || abort '! Payload is damaged or contains unlisted files'
set_perm_recursive "$MODPATH" 0 0 0755 0644
for script in "$MODPATH"/*.sh; do set_perm "$script" 0 0 0755; done
onyx_label_payload_root "$MODPATH" || abort '! Cannot preserve installed payload labels'
umask 077
mkdir -p "$ONYX_STATE" "${ONYX_WATCHER%/*}" || abort '! Cannot create trial state'
for script in common.sh guard-service.sh; do
    cp "$MODPATH/$script" "$ONYX_STATE/$script" || abort '! Cannot prepare watchdog'
    chmod 0700 "$ONYX_STATE/$script"
done
cat > "$ONYX_WATCHER" <<'WATCHER'
#!/system/bin/sh
# Onyx brightness watchdog; owned by onyx_stock_brightness_test.
exec /system/bin/sh /data/adb/onyx-stock-brightness-test/guard-service.sh
WATCHER
chmod 0700 "$ONYX_WATCHER" || abort '! Cannot enable independent watchdog'
touch "$MODPATH/disable"
rm -f "$ONYX_STATE/armed" "$ONYX_STATE/accepted"
ui_print '- Installed disabled; arm.sh performs the final baseline check before a trial boot'
