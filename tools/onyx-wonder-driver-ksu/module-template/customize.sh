#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
WDR_MOD=$MODPATH
. "$MODPATH/common.sh"
wdr_device_matches || abort 'Requires Onyx Android 17 and the frozen 6.18.63 kernel.'
wdr_payload_matches || abort 'Reviewed QCA payload is absent or its SHA256 differs.'
wdr_stock_matches || abort 'The installed QCA module differs from the frozen stock SHA256.'
set_perm_recursive "$MODPATH" 0 0 0755 0644
for wdr_script in "$MODPATH"/*.sh; do set_perm "$wdr_script" 0 0 0755; done
chcon u:object_r:vendor_file:s0 "$MODPATH/payload/qca_cld3_wcn7750.ko" \
    || abort 'Cannot apply the reviewed vendor module file label.'
ui_print 'No driver reload occurs during installation.'
ui_print 'On next boot, a synchronous guarded post-fs-data hook reloads only QCA.'
ui_print 'Disable and reboot to use the vendor stock driver again.'
