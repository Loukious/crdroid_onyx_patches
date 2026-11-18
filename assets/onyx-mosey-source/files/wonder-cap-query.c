/* SPDX-License-Identifier: Apache-2.0 */
/* Read-only Wonder capability and wlan0 regulatory queries. */
#define _GNU_SOURCE
#include <errno.h>
#include <linux/genetlink.h>
#include <linux/netlink.h>
#include <linux/nl80211.h>
#include <poll.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>
#include "wonder-cap-query.h"

#define WONDER_VENDOR 0x001a11U
#define WONDER_GET_CAP 8U
#define CAP_CH_HOPPING 4U
#define CAP_HBS 5U
#define CAP_NSS 6U
#define CAP_MAX_SWITCH_US 8U
#define QUERY_DEADLINE_MS 1500

static int64_t monotonic_ms(void)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts)) return -1;
    return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static int add_attr(void *packet, size_t capacity, uint16_t type,
                    const void *data, size_t size)
{
    struct nlmsghdr *nlh = packet;
    if (size && !data) return -EINVAL;
    size_t at = NLMSG_ALIGN(nlh->nlmsg_len), len = NLA_HDRLEN + size;
    if (len > UINT16_MAX || at > capacity || NLA_ALIGN(len) > capacity - at)
        return -EMSGSIZE;
    struct nlattr *a = (struct nlattr *)((uint8_t *)packet + at);
    a->nla_type = type;
    a->nla_len = (uint16_t)len;
    if (size) memcpy((uint8_t *)a + NLA_HDRLEN, data, size);
    memset((uint8_t *)a + len, 0, NLA_ALIGN(len) - len);
    nlh->nlmsg_len = (uint32_t)(at + NLA_ALIGN(len));
    return 0;
}

/* Reject malformed attributes and duplicate requested scalars. */
static int find_attr(const void *data, size_t size, uint16_t type,
                     const void **value, size_t *length)
{
    const uint8_t *cursor = data;
    bool found = false;
    while (size) {
        if (size < NLA_HDRLEN) return -EBADMSG;
        const struct nlattr *a = (const struct nlattr *)cursor;
        if (a->nla_len < NLA_HDRLEN || a->nla_len > size ||
            (size_t)NLA_ALIGN(a->nla_len) > size) return -EBADMSG;
        if ((a->nla_type & NLA_TYPE_MASK) == type) {
            if (found) return -EBADMSG;
            *value = cursor + NLA_HDRLEN;
            *length = a->nla_len - NLA_HDRLEN;
            found = true;
        }
        size -= NLA_ALIGN(a->nla_len);
        cursor += NLA_ALIGN(a->nla_len);
    }
    return found ? 0 : -ENODATA;
}

/* The new interface/regulatory identity fields use plain native-endian
 * scalars and strings. Reject nested or network-byte-order impostors.
 */
static int find_plain_attr(const void *data, size_t size, uint16_t type,
                           const void **value, size_t *length)
{
    int rc = find_attr(data, size, type, value, length);
    if (rc) return rc;
    const uint8_t *cursor = data;
    while (size) {
        const struct nlattr *a = (const struct nlattr *)cursor;
        if ((a->nla_type & NLA_TYPE_MASK) == type && a->nla_type != type)
            return -EBADMSG;
        size -= NLA_ALIGN(a->nla_len);
        cursor += NLA_ALIGN(a->nla_len);
    }
    return 0;
}

static int plain_u32(const void *data, size_t size, uint16_t type, uint32_t *output)
{
    const void *value;
    size_t length;
    int rc = find_plain_attr(data, size, type, &value, &length);
    if (rc) return rc;
    if (length != sizeof(*output)) return -EBADMSG;
    memcpy(output, value, sizeof(*output));
    return 0;
}

static int receive_responses(int fd, uint32_t seq, uint16_t type,
                             uint8_t command, bool dump,
                             int (*consume)(const void *, size_t, void *),
                             void *context)
{
    const int64_t started = monotonic_ms();
    if (started < 0) return -errno;
    const int64_t deadline = started + QUERY_DEADLINE_MS;
    _Alignas(struct nlmsghdr) uint8_t packet[65536];
    for (;;) {
        const int64_t now = monotonic_ms();
        if (now < 0) return -errno;
        int64_t remaining = deadline - now;
        if (remaining <= 0) return -ETIMEDOUT;
        struct pollfd pfd = {.fd = fd, .events = POLLIN};
        int rc = poll(&pfd, 1, (int)remaining);
        if (rc < 0) { if (errno == EINTR) continue; return -errno; }
        if (!rc) return -ETIMEDOUT;
        struct sockaddr_nl source = {0};
        struct iovec iov = {.iov_base = packet, .iov_len = sizeof(packet)};
        struct msghdr msg = {.msg_name = &source, .msg_namelen = sizeof(source),
                             .msg_iov = &iov, .msg_iovlen = 1};
        ssize_t count = recvmsg(fd, &msg, 0);
        if (count < 0) { if (errno == EINTR) continue; return -errno; }
        if (msg.msg_flags & MSG_TRUNC) return -EMSGSIZE;
        if (source.nl_pid != 0) return -EPROTO;
        size_t left = (size_t)count;
        for (struct nlmsghdr *h = (struct nlmsghdr *)packet; left;) {
            if (left < NLMSG_HDRLEN || h->nlmsg_len < NLMSG_HDRLEN ||
                h->nlmsg_len > left || NLMSG_ALIGN(h->nlmsg_len) > left)
                return -EBADMSG;
            if (h->nlmsg_seq == seq) {
                if (h->nlmsg_flags & NLM_F_DUMP_INTR) return -EAGAIN;
                if (h->nlmsg_type == NLMSG_ERROR) {
                    if (h->nlmsg_len < NLMSG_LENGTH(sizeof(struct nlmsgerr)))
                        return -EBADMSG;
                    struct nlmsgerr error;
                    memcpy(&error, NLMSG_DATA(h), sizeof(error));
                    if (error.error) return error.error;
                } else if (h->nlmsg_type == type) {
                    if (h->nlmsg_len < NLMSG_LENGTH(GENL_HDRLEN)) return -EBADMSG;
                    const struct genlmsghdr *g = NLMSG_DATA(h);
                    if (g->cmd != command) return -EPROTO;
                    size_t payload = h->nlmsg_len - NLMSG_HDRLEN - GENL_HDRLEN;
                    rc = consume((const uint8_t *)g + GENL_HDRLEN, payload, context);
                    if (rc) return rc;
                    if (!dump) return 0;
                } else if (h->nlmsg_type == NLMSG_DONE) {
                    size_t payload = h->nlmsg_len - NLMSG_HDRLEN;
                    if (payload && payload < sizeof(int32_t)) return -EBADMSG;
                    if (payload) {
                        int32_t error;
                        memcpy(&error, NLMSG_DATA(h), sizeof(error));
                        if (error) return error;
                    }
                    return dump ? 0 : -ENODATA;
                }
            }
            size_t next = NLMSG_ALIGN(h->nlmsg_len);
            left -= next;
            h = (struct nlmsghdr *)((uint8_t *)h + next);
        }
    }
}

struct reply_buffer { uint8_t *data; size_t size; };
static int copy_reply(const void *data, size_t size, void *context)
{
    struct reply_buffer *reply = context;
    if (size > reply->size) return -EMSGSIZE;
    memcpy(reply->data, data, size);
    reply->size = size;
    return 0;
}

static int receive_reply(int fd, uint32_t seq, uint16_t type,
                         uint8_t command, uint8_t *output, size_t *output_size)
{
    struct reply_buffer reply = {.data = output, .size = *output_size};
    int rc = receive_responses(fd, seq, type, command, false, copy_reply, &reply);
    if (!rc) *output_size = reply.size;
    return rc;
}

struct wiphy_match { uint32_t index; bool found; };
static int match_wiphy(const void *data, size_t size, void *context)
{
    struct wiphy_match *match = context;
    const void *value;
    size_t length;
    int rc = find_attr(data, size, NL80211_ATTR_WIPHY_NAME, &value, &length);
    if (rc == -ENODATA) return 0; /* A split continuation may omit the name. */
    if (rc) return rc;
    if (!length || ((const uint8_t *)value)[length - 1] != 0) return -EBADMSG;
    if (length != sizeof("wonder") || memcmp(value, "wonder", sizeof("wonder")))
        return 0;
    rc = find_attr(data, size, NL80211_ATTR_WIPHY, &value, &length);
    if (rc) return rc;
    if (length != sizeof(uint32_t)) return -EBADMSG;
    uint32_t index;
    memcpy(&index, value, sizeof(index));
    if (match->found && match->index != index) return -EPROTO;
    match->found = true;
    match->index = index;
    return 0;
}

static void init_request(uint8_t *packet, uint16_t type, uint8_t cmd, uint32_t seq)
{
    memset(packet, 0, 512);
    struct nlmsghdr *h = (struct nlmsghdr *)packet;
    h->nlmsg_len = NLMSG_LENGTH(GENL_HDRLEN);
    h->nlmsg_type = type;
    h->nlmsg_flags = NLM_F_REQUEST | NLM_F_ACK;
    h->nlmsg_seq = seq;
    struct genlmsghdr *g = NLMSG_DATA(h);
    g->cmd = cmd;
    g->version = 1;
}

static int send_request(int fd, const uint8_t *packet)
{
    const struct nlmsghdr *h = (const struct nlmsghdr *)packet;
    struct sockaddr_nl kernel = {.nl_family = AF_NETLINK};
    ssize_t sent = sendto(fd, packet, h->nlmsg_len, 0,
                          (struct sockaddr *)&kernel, sizeof(kernel));
    return sent < 0 ? -errno : ((size_t)sent == h->nlmsg_len ? 0 : -EIO);
}

static int check_optional_u32(const void *data, size_t size,
                               uint16_t type, uint32_t expected)
{
    const void *value;
    size_t length;
    int rc = find_attr(data, size, type, &value, &length);
    if (rc == -ENODATA) return 0;
    if (rc) return rc;
    if (length != sizeof(uint32_t)) return -EBADMSG;
    uint32_t actual;
    memcpy(&actual, value, sizeof(actual));
    return actual == expected ? 0 : -EPROTO;
}

static int parse_caps(const void *reply, size_t reply_size, uint32_t wiphy,
                      struct wonder_caps *caps)
{
    const void *value;
    size_t value_size;
    int rc;
    if ((rc = check_optional_u32(reply, reply_size, NL80211_ATTR_WIPHY, wiphy)) ||
        (rc = check_optional_u32(reply, reply_size, NL80211_ATTR_VENDOR_ID, WONDER_VENDOR)) ||
        (rc = check_optional_u32(reply, reply_size, NL80211_ATTR_VENDOR_SUBCMD, WONDER_GET_CAP)))
        return rc;
    rc = find_attr(reply, reply_size, NL80211_ATTR_VENDOR_DATA, &value, &value_size);
    if (rc) return rc;
    const void *fields = value;
    size_t fields_size = value_size;
    struct wonder_caps parsed_caps = {0};
    rc = find_attr(fields, fields_size, CAP_CH_HOPPING, &value, &value_size);
    if (rc) return rc;
    if (value_size != 1 || *(const uint8_t *)value > 1) return -EBADMSG;
    parsed_caps.hopping = *(const uint8_t *)value != 0;
    rc = find_attr(fields, fields_size, CAP_HBS, &value, &value_size);
    if (rc) return rc;
    if (value_size != 1 || *(const uint8_t *)value > 1) return -EBADMSG;
    parsed_caps.hbs = *(const uint8_t *)value != 0;
    rc = find_attr(fields, fields_size, CAP_NSS, &value, &value_size);
    if (rc) return rc;
    if (value_size != 1) return -EBADMSG;
    parsed_caps.nss = *(const uint8_t *)value;
    rc = find_attr(fields, fields_size, CAP_MAX_SWITCH_US, &value, &value_size);
    if (rc) return rc;
    if (value_size != 4) return -EBADMSG;
    memcpy(&parsed_caps.max_switch_us, value, sizeof(parsed_caps.max_switch_us));
    *caps = parsed_caps;
    return 0;
}

static int parse_wlan_interface(const void *reply, size_t reply_size,
                                uint32_t expected_ifindex,
                                struct wonder_regulatory *regulatory)
{
    struct wonder_regulatory parsed = {0};
    const void *name;
    size_t length;
    int rc = plain_u32(reply, reply_size, NL80211_ATTR_IFINDEX, &parsed.ifindex);
    if (rc) return rc;
    if (!expected_ifindex || parsed.ifindex != expected_ifindex) return -EPROTO;
    rc = find_plain_attr(reply, reply_size, NL80211_ATTR_IFNAME, &name, &length);
    if (rc) return rc;
    if (length != sizeof("wlan0") || memcmp(name, "wlan0", sizeof("wlan0")))
        return -EPROTO;
    uint32_t iftype;
    rc = plain_u32(reply, reply_size, NL80211_ATTR_IFTYPE, &iftype);
    if (rc) return rc;
    if (iftype != NL80211_IFTYPE_STATION) return -EPROTO;
    rc = plain_u32(reply, reply_size, NL80211_ATTR_WIPHY, &parsed.wiphy);
    if (rc) return rc;
    *regulatory = parsed;
    return 0;
}

static int parse_reg_country(const void *reply, size_t reply_size,
                             struct wonder_regulatory *regulatory)
{
    uint32_t wiphy;
    const void *country;
    size_t length;
    int rc = plain_u32(reply, reply_size, NL80211_ATTR_WIPHY, &wiphy);
    if (rc) return rc;
    if (wiphy != regulatory->wiphy) return -EPROTO;
    rc = find_plain_attr(reply, reply_size, NL80211_ATTR_REG_ALPHA2, &country, &length);
    if (rc) return rc;
    if (length != sizeof(regulatory->alpha2)) return -EBADMSG;
    const uint8_t *alpha2 = country;
    if (alpha2[0] < 'A' || alpha2[0] > 'Z' ||
        alpha2[1] < 'A' || alpha2[1] > 'Z' || alpha2[2]) return -EBADMSG;
    memcpy(regulatory->alpha2, alpha2, sizeof(regulatory->alpha2));
    return 0;
}

struct wlan_match { struct wonder_regulatory regulatory; bool found; };
static int match_wlan_interface(const void *reply, size_t reply_size, void *context)
{
    struct wlan_match *match = context;
    const void *name;
    size_t length;
    int rc = find_plain_attr(reply, reply_size, NL80211_ATTR_IFNAME, &name, &length);
    if (rc == -ENODATA) return 0; /* A non-netdev wireless interface has no name. */
    if (rc) return rc;
    if (!length || ((const uint8_t *)name)[length - 1]) return -EBADMSG;
    if (length != sizeof("wlan0") || memcmp(name, "wlan0", sizeof("wlan0")))
        return 0;
    if (match->found) return -EPROTO;
    uint32_t ifindex;
    rc = plain_u32(reply, reply_size, NL80211_ATTR_IFINDEX, &ifindex);
    if (rc) return rc;
    rc = parse_wlan_interface(reply, reply_size, ifindex, &match->regulatory);
    if (!rc) match->found = true;
    return rc;
}

int query_wlan_regulatory(struct wonder_regulatory *regulatory)
{
    if (!regulatory) return -EINVAL;
    memset(regulatory, 0, sizeof(*regulatory));
    /* Private nonblocking socket bounds sends and avoids a poll/recv stall.
     * Each of the three replies has the existing 1500 ms total deadline.
     */
    int fd = socket(AF_NETLINK, SOCK_RAW | SOCK_CLOEXEC | SOCK_NONBLOCK, NETLINK_GENERIC);
    if (fd < 0) return -errno;
    struct sockaddr_nl local = {.nl_family = AF_NETLINK};
    int rc = bind(fd, (struct sockaddr *)&local, sizeof(local));
    if (rc < 0) { rc = -errno; goto done; }
    _Alignas(struct nlmsghdr) uint8_t request[512], reply[8192];
    size_t reply_size = sizeof(reply), length;
    const void *value;
    struct wonder_regulatory parsed = {0};
    init_request(request, GENL_ID_CTRL, CTRL_CMD_GETFAMILY, 1);
    rc = add_attr(request, sizeof(request), CTRL_ATTR_FAMILY_NAME, "nl80211", sizeof("nl80211"));
    if (rc) goto done;
    rc = send_request(fd, request);
    if (rc) goto done;
    rc = receive_reply(fd, 1, GENL_ID_CTRL, CTRL_CMD_NEWFAMILY, reply, &reply_size);
    if (rc) goto done;
    rc = find_plain_attr(reply, reply_size, CTRL_ATTR_FAMILY_NAME, &value, &length);
    if (rc) goto done;
    if (length != sizeof("nl80211") || memcmp(value, "nl80211", sizeof("nl80211"))) {
        rc = -EPROTO; goto done;
    }
    rc = find_plain_attr(reply, reply_size, CTRL_ATTR_FAMILY_ID, &value, &length);
    if (rc) goto done;
    if (length != sizeof(uint16_t)) { rc = -EBADMSG; goto done; }
    uint16_t family;
    memcpy(&family, value, sizeof(family));
    if (family < GENL_MIN_ID) { rc = -EPROTO; goto done; }

    /* Identify the real wlan0 using only the existing generic-netlink socket
     * permissions. Bionic if_nametoindex instead uses a UDP ioctl that the
     * Mosey domain does not authorize. A complete dump validates name, role,
     * index and wiphy together and rejects a racing or duplicate interface.
     */
    struct wlan_match match = {0};
    init_request(request, family, NL80211_CMD_GET_INTERFACE, 2);
    ((struct nlmsghdr *)request)->nlmsg_flags |= NLM_F_DUMP;
    rc = send_request(fd, request);
    if (rc) goto done;
    rc = receive_responses(fd, 2, family, NL80211_CMD_NEW_INTERFACE, true,
                           match_wlan_interface, &match);
    if (rc) goto done;
    if (!match.found) { rc = -ENODEV; goto done; }
    parsed = match.regulatory;

    init_request(request, family, NL80211_CMD_GET_REG, 3);
    rc = add_attr(request, sizeof(request), NL80211_ATTR_WIPHY, &parsed.wiphy, sizeof(parsed.wiphy));
    if (rc) goto done;
    rc = send_request(fd, request);
    if (rc) goto done;
    reply_size = sizeof(reply);
    rc = receive_reply(fd, 3, family, NL80211_CMD_GET_REG, reply, &reply_size);
    if (rc) goto done;
    rc = parse_reg_country(reply, reply_size, &parsed);
    if (!rc) *regulatory = parsed;
done:
    close(fd);
    return rc;
}

int query_wonder_caps(struct wonder_caps *caps)
{
    if (!caps) return -EINVAL;
    memset(caps, 0, sizeof(*caps));
    int fd = socket(AF_NETLINK, SOCK_RAW | SOCK_CLOEXEC, NETLINK_GENERIC);
    if (fd < 0) return -errno;
    struct sockaddr_nl local = {.nl_family = AF_NETLINK};
    int rc = bind(fd, (struct sockaddr *)&local, sizeof(local));
    if (rc < 0) { rc = -errno; goto done; }
    _Alignas(struct nlmsghdr) uint8_t request[512], reply[8192];
    size_t reply_size = sizeof(reply), value_size = 0;
    const void *value = NULL;
    init_request(request, GENL_ID_CTRL, CTRL_CMD_GETFAMILY, 1);
    rc = add_attr(request, sizeof(request), CTRL_ATTR_FAMILY_NAME, "nl80211", 8);
    if (rc) goto done;
    rc = send_request(fd, request);
    if (rc) goto done;
    rc = receive_reply(fd, 1, GENL_ID_CTRL, CTRL_CMD_NEWFAMILY, reply, &reply_size);
    if (rc) goto done;
    rc = find_attr(reply, reply_size, CTRL_ATTR_FAMILY_ID, &value, &value_size);
    if (rc) goto done;
    if (value_size != sizeof(uint16_t)) { rc = -EBADMSG; goto done; }
    uint16_t family;
    memcpy(&family, value, sizeof(family));

    /* A complete split GET_WIPHY dump identifies the exact radio through the
     * existing nl80211 socket permissions. No sysfs access or netdev is needed.
     */
    struct wiphy_match match = {0};
    init_request(request, family, NL80211_CMD_GET_WIPHY, 2);
    ((struct nlmsghdr *)request)->nlmsg_flags |= NLM_F_DUMP;
    rc = add_attr(request, sizeof(request), NL80211_ATTR_SPLIT_WIPHY_DUMP, NULL, 0);
    if (rc) goto done;
    rc = send_request(fd, request);
    if (rc) goto done;
    rc = receive_responses(fd, 2, family, NL80211_CMD_NEW_WIPHY, true, match_wiphy, &match);
    if (rc) goto done;
    if (!match.found) { rc = -ENODEV; goto done; }
    uint32_t wiphy = match.index;

    init_request(request, family, NL80211_CMD_VENDOR, 3);
    uint32_t vendor = WONDER_VENDOR, subcmd = WONDER_GET_CAP;
    if ((rc = add_attr(request, sizeof(request), NL80211_ATTR_WIPHY, &wiphy, sizeof(wiphy))) ||
        (rc = add_attr(request, sizeof(request), NL80211_ATTR_VENDOR_ID, &vendor, sizeof(vendor))) ||
        (rc = add_attr(request, sizeof(request), NL80211_ATTR_VENDOR_SUBCMD, &subcmd, sizeof(subcmd))))
        goto done;
    rc = send_request(fd, request);
    if (rc) goto done;
    reply_size = sizeof(reply);
    rc = receive_reply(fd, 3, family, NL80211_CMD_VENDOR, reply, &reply_size);
    if (rc) goto done;
    rc = parse_caps(reply, reply_size, wiphy, caps);
done:
    close(fd);
    return rc;
}

#ifdef WONDER_CAP_QUERY_MAIN
int main(void)
{
    struct wonder_caps caps;
    int rc = query_wonder_caps(&caps);
    if (rc) { fprintf(stderr, "Wonder GET_CAP failed: %s (%d)\n", strerror(-rc), rc); return 1; }
    printf("{\"channel_hopping\":%s,\"hbs_support\":%s,\"nss\":%u,\"max_switch_us\":%u}\n",
           caps.hopping ? "true" : "false", caps.hbs ? "true" : "false",
           caps.nss, caps.max_switch_us);
    return 0;
}
#elif defined(WONDER_REG_QUERY_MAIN)
int main(void)
{
    struct wonder_regulatory regulatory;
    int rc = query_wlan_regulatory(&regulatory);
    if (rc) { fprintf(stderr, "wlan0 regulatory query failed: %s (%d)\n", strerror(-rc), rc); return 1; }
    printf("{\"ifindex\":%u,\"wiphy\":%u,\"country\":\"%.2s\"}\n",
           regulatory.ifindex, regulatory.wiphy, regulatory.alpha2);
    return 0;
}
#endif
