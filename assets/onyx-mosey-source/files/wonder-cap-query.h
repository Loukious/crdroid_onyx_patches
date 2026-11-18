/* SPDX-License-Identifier: Apache-2.0 */
#ifndef ONYX_WONDER_CAP_QUERY_H
#define ONYX_WONDER_CAP_QUERY_H
#include <stdbool.h>
#include <stdint.h>

struct wonder_caps {
    bool hopping;
    bool hbs;
    uint8_t nss;
    uint32_t max_switch_us;
};

/* Returns zero only after a successful, well-formed real GET_CAP reply. */
int query_wonder_caps(struct wonder_caps *caps);

struct wonder_regulatory {
    uint32_t ifindex;
    uint32_t wiphy;
    char alpha2[3];
};

/* Read the real wlan0 vendor wiphy regulatory domain. No regulatory changes.
 * Returns zero only for a matching interface/wiphy and uppercase ISO alpha2.
 * Output is cleared on failure; no world/default-country fallback is used.
 */
int query_wlan_regulatory(struct wonder_regulatory *regulatory);
#endif
