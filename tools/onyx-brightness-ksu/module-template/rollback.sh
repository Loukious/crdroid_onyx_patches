#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
ONYX_MOD=${0%/*}
. "$ONYX_MOD/common.sh"
touch "$ONYX_MOD/disable"
rm -f "$ONYX_STATE/accepted" "$ONYX_STATE/armed"
sync
echo 'Brightness module disabled; the next full reboot restores the base artifacts'
[ "${1:-}" != --reboot ] || exec "$ONYX_REBOOT"
