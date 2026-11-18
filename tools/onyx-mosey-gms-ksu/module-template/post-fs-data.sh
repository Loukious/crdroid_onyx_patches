#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
. "${0%/*}/common.sh"
mosey_init || exit 0
mosey_device_matches || exit 0
mosey_policy_apply || { mosey_log 'Native policy update rejected; early flag update skipped.'; exit 0; }
# DE is available before unlock. No CE path is opened in this stage.
mosey_de_state=$(mosey_inspect "$MOSEY_DE" de 2>/dev/null) || exit 0
case "$mosey_de_state" in absent|false|unlinked) :;; *) exit 0;; esac
# If package manager is not ready, defer rather than trusting a cached APK version.
mosey_compatible || exit 0
mosey_early=$(mosey_apply_database "$MOSEY_DE" de) || exit 0
[ "$mosey_early" != changed ] || cat /proc/sys/kernel/random/boot_id > "$MOSEY_STATE/de-changed-boot"
mosey_log "Early DE override: $mosey_early"
