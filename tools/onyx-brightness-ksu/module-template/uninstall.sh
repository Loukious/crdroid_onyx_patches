#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
ONYX_MOD=${0%/*}
. "$ONYX_MOD/common.sh"
if grep -Fq '# Onyx brightness watchdog; owned by onyx_stock_brightness_test.' \
        "$ONYX_WATCHER" 2>/dev/null; then
    rm -f "$ONYX_WATCHER"
fi
rm -f "$ONYX_STATE/accepted" "$ONYX_STATE/armed"
echo 'Brightness trial removed; diagnostics retained under /data/adb/onyx-stock-brightness-test'
