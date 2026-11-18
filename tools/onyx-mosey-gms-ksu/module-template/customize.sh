#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
MODDIR=$MODPATH
. "$MODPATH/common.sh"
MOSEY_MOD=$MODPATH
mosey_init || abort 'Root and a native Android sqlite3 command are required.'
mosey_compatible || abort 'This module requires Onyx Android 17 and GMS 26.46.30 (264630035).'
mosey_app_compatible || abort 'This module requires the inspected Mosey APK version 60715.'
set_perm_recursive "$MODPATH" 0 0 0755 0644
for mosey_script in "$MODPATH"/*.sh; do set_perm "$mosey_script" 0 0 0755; done
set_perm "$MODPATH/bin/onyx-mosey-nlmsg" 0 0 0755
[ -f "$MODPATH/bin/onyx-mosey-cache" ] || abort 'The verified shared-cache helper is required.'
set_perm "$MODPATH/bin/onyx-mosey-cache" 0 0 0755
if [ -f "$MODPATH/system/system_ext/lib64/libmosey_onyx_config.so" ]; then
    chcon u:object_r:system_lib_file:s0 "$MODPATH/system/system_ext/lib64/libmosey_onyx_config.so" \
        || abort 'Cannot label the native Mosey adapter.'
fi
ui_print 'Nearby/Mosey flags and shared-cache overrides use private scoped backups.'
ui_print 'Disable stops future boot actions; run rollback.sh to undo a module-created override.'
