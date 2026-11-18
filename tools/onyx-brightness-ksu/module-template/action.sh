#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
echo 'Rolling back the brightness trial and rebooting to the base ROM'
exec /system/bin/sh "${0%/*}/rollback.sh" --reboot
