#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Deliberately synchronous: Android Wi-Fi must not start during replacement.
WDR_MOD=${0%/*}
. "$WDR_MOD/common.sh"
wdr_init || exit 0
wdr_reload || exit 0
