#!/usr/bin/env python3
"""Host regressions for real-wiphy regulatory selection and FFI argument preservation."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[2] / "assets/onyx-mosey-source/files"

PARSER_FIXTURE = r'''
#define _GNU_SOURCE
#include "wonder-cap-query.c"
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    const char *test = argv[1];
    _Alignas(struct nlmsghdr) uint8_t packet[512];
    uint32_t index = 11, phy = 7, station = NL80211_IFTYPE_STATION;
    struct wonder_regulatory output = {.ifindex = index, .wiphy = phy};
    int regulatory = !strncmp(test, "reg-", 4), rc;
    init_request(packet, 42, regulatory ? NL80211_CMD_GET_REG : NL80211_CMD_NEW_INTERFACE, 9);
    if (!regulatory) {
        if (!strcmp(test, "interface-wrong-index")) index++;
        if (!strcmp(test, "interface-zero-expected")) index = 0;
        if (strcmp(test, "interface-missing-index"))
            add_attr(packet, sizeof(packet), NL80211_ATTR_IFINDEX, &index, sizeof(index));
        const char *name = !strcmp(test, "interface-wrong-name") ? "p2p0" : "wlan0";
        size_t name_size = strlen(name) + 1;
        if (!strcmp(test, "interface-name-without-nul")) name_size--;
        add_attr(packet, sizeof(packet), NL80211_ATTR_IFNAME, name, name_size);
        if (!strcmp(test, "interface-wrong-role")) station = NL80211_IFTYPE_AP;
        if (strcmp(test, "interface-missing-role"))
            add_attr(packet, sizeof(packet), NL80211_ATTR_IFTYPE, &station, sizeof(station));
        if (strcmp(test, "interface-missing-wiphy"))
            add_attr(packet, sizeof(packet), NL80211_ATTR_WIPHY, &phy, sizeof(phy));
        if (!strcmp(test, "interface-duplicate-wiphy"))
            add_attr(packet, sizeof(packet), NL80211_ATTR_WIPHY, &phy, sizeof(phy));
        if (!strcmp(test, "interface-truncated"))
            ((struct nlmsghdr *)packet)->nlmsg_len--;
        if (!strcmp(test, "interface-flagged-wiphy")) {
            struct nlmsghdr *h = (struct nlmsghdr *)packet;
            struct nlattr *last = (struct nlattr *)(packet + h->nlmsg_len - NLA_ALIGN(NLA_HDRLEN + sizeof(phy)));
            last->nla_type |= NLA_F_NESTED;
        }
    } else {
        if (!strcmp(test, "reg-wrong-wiphy")) phy++;
        if (strcmp(test, "reg-missing-wiphy"))
            add_attr(packet, sizeof(packet), NL80211_ATTR_WIPHY, &phy, sizeof(phy));
        if (!strcmp(test, "reg-duplicate-wiphy"))
            add_attr(packet, sizeof(packet), NL80211_ATTR_WIPHY, &phy, sizeof(phy));
        const char *country = "US";
        size_t country_size = 3;
        if (!strcmp(test, "reg-lowercase")) country = "us";
        if (!strcmp(test, "reg-world")) country = "00";
        if (!strcmp(test, "reg-no-nul")) country_size = 2;
        if (!strcmp(test, "reg-long")) { country = "USA"; country_size = 4; }
        if (strcmp(test, "reg-missing-country"))
            add_attr(packet, sizeof(packet), NL80211_ATTR_REG_ALPHA2, country, country_size);
        if (!strcmp(test, "reg-duplicate-country"))
            add_attr(packet, sizeof(packet), NL80211_ATTR_REG_ALPHA2, country, country_size);
        if (!strcmp(test, "reg-truncated"))
            ((struct nlmsghdr *)packet)->nlmsg_len--;
        if (!strcmp(test, "reg-flagged-country")) {
            struct nlmsghdr *h = (struct nlmsghdr *)packet;
            struct nlattr *last = (struct nlattr *)(packet + h->nlmsg_len - NLA_ALIGN(NLA_HDRLEN + country_size));
            last->nla_type |= NLA_F_NET_BYTEORDER;
        }
    }
    struct nlmsghdr *h = (struct nlmsghdr *)packet;
    const void *attrs = packet + NLMSG_HDRLEN + GENL_HDRLEN;
    size_t size = h->nlmsg_len - NLMSG_HDRLEN - GENL_HDRLEN;
    if (regulatory) rc = parse_reg_country(attrs, size, &output);
    else {
        memset(&output, 0x5a, sizeof(output));
        rc = parse_wlan_interface(attrs, size, !strcmp(test, "interface-zero-expected") ? 0 : 11, &output);
    }
    printf("{\"rc\":%d,\"ifindex\":%u,\"wiphy\":%u,\"country\":\"%.2s\"}\n",
           rc, output.ifindex, output.wiphy, rc == 0 ? output.alpha2 : "");
    return 0;
}
'''

WRAPPER_FIXTURE = r'''
#define _GNU_SOURCE
#include <errno.h>
#include <stdio.h>
#include <stdarg.h>
#include "config.c"
static int query_calls, start_calls, query_failure;
static const void *expected_channels;
static const uint8_t *expected_config;
static size_t expected_length;
static int prefix_ok, suffix_ok, channels_ok, args_ok;
static char received_country[3];
int __android_log_print(int priority, const char *tag, const char *format, ...) {
    (void)priority; (void)tag; (void)format; return 0;
}
int query_wlan_regulatory(struct wonder_regulatory *output) {
    query_calls++;
    memset(output, 0, sizeof(*output));
    if (query_failure) return -EIO;
    output->ifindex = 11; output->wiphy = 7;
    memcpy(output->alpha2, "US", 3);
    return 0;
}
static void *capture(const void *channels, size_t count, uint32_t mdns,
                     const void *country, uint32_t radio, const uint8_t *config, size_t length) {
    start_calls++;
    channels_ok = channels == expected_channels && count == 1 && ((const uint8_t *)channels)[0] == 6;
    args_ok = mdns == 1234 && radio == 2;
    prefix_ok = length == expected_length + 2 && !memcmp(config, expected_config, expected_length);
    suffix_ok = config[length-2] == 0x28 && config[length-1] == 1;
    if (country && strlen((const char *)country) == 2)
        memcpy(received_country, country, 3);
    return (void *)(uintptr_t)0x1234;
}
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    const char *test = argv[1];
    const uint8_t channels[] = {6};
    const uint8_t config[] = {0x10, 0x85, 0x13, 0x18, 1, 0x28, 1, 0x38, 2};
    const char original_country[] = "TN";
    expected_channels = channels; expected_config = config; expected_length = sizeof(config);
    atomic_store(&original_start, strcmp(test, "missing-original") ? capture : NULL);
    query_failure = !strcmp(test, "query-failure");
    const uint8_t *input = !strcmp(test, "null-config") ? NULL : config;
    size_t length = !strcmp(test, "oversize-config") ? SIZE_MAX : sizeof(config);
    void *result = start_wonder(channels, 1, 1234, original_country, 0, input, length);
    printf("{\"returned\":%s,\"query_calls\":%d,\"start_calls\":%d,"
           "\"country\":\"%s\",\"channels_preserved\":%s,\"args_preserved\":%s,"
           "\"config_preserved\":%s,\"hopping_extension\":%s,\"original_country\":\"%s\"}\n",
           result == (void *)(uintptr_t)0x1234 ? "true" : "false", query_calls, start_calls,
           received_country, channels_ok ? "true" : "false", args_ok ? "true" : "false",
           prefix_ok ? "true" : "false", suffix_ok ? "true" : "false", original_country);
    return 0;
}
'''

QUERY_FIXTURE = r'''
#define _GNU_SOURCE
#define socket fake_socket
#define bind fake_bind
#define close fake_close
#define sendto fake_sendto
#define recvmsg fake_recvmsg
#define poll fake_poll
#define clock_gettime fake_clock_gettime
#include "wonder-cap-query.c"
static const char *scenario;
static uint32_t last_sequence;
static int socket_calls, requests, closes, nonblocking;
static long ticks;
int fake_socket(int domain, int type, int protocol) {
    socket_calls++;
    nonblocking = !!(type & SOCK_NONBLOCK);
    if (domain != AF_NETLINK || protocol != NETLINK_GENERIC || !nonblocking) { errno = EPROTO; return -1; }
    if (!strcmp(scenario, "socket-denied")) { errno = EACCES; return -1; }
    return 99;
}
int fake_bind(int fd, const struct sockaddr *address, socklen_t length) {
    if (fd != 99 || length != sizeof(struct sockaddr_nl) || address->sa_family != AF_NETLINK) { errno = EPROTO; return -1; }
    if (!strcmp(scenario, "bind-denied")) { errno = EACCES; return -1; }
    return 0;
}
int fake_close(int fd) { if (fd != 99) return -1; closes++; return 0; }
int fake_clock_gettime(clockid_t clock, struct timespec *value) {
    if (clock != CLOCK_MONOTONIC) return -1;
    ticks += 50;
    value->tv_sec = ticks / 1000; value->tv_nsec = ticks % 1000 * 1000000;
    return 0;
}
int fake_poll(struct pollfd *fds, nfds_t count, int duration) {
    if (count != 1 || fds->fd != 99 || duration < 1 || duration > QUERY_DEADLINE_MS) { errno = EPROTO; return -1; }
    if (!strcmp(scenario, "timeout")) return 0;
    fds->revents = POLLIN; return 1;
}
ssize_t fake_sendto(int fd, const void *data, size_t length, int flags,
                    const struct sockaddr *address, socklen_t address_length) {
    (void)flags;
    if (fd != 99 || address_length != sizeof(struct sockaddr_nl) ||
        ((const struct sockaddr_nl *)address)->nl_pid) { errno = EPROTO; return -1; }
    const struct nlmsghdr *h = data;
    const struct genlmsghdr *g = NLMSG_DATA(h);
    const void *attrs = (const uint8_t *)g + GENL_HDRLEN;
    size_t attr_size = length - NLMSG_HDRLEN - GENL_HDRLEN, size;
    const void *value;
    uint32_t identity;
    requests++;
    if (h->nlmsg_seq != (uint32_t)requests || h->nlmsg_len != length) { errno = EPROTO; return -1; }
    last_sequence = h->nlmsg_seq;
    if (last_sequence == 1) {
        if (h->nlmsg_type != GENL_ID_CTRL || g->cmd != CTRL_CMD_GETFAMILY ||
            find_plain_attr(attrs, attr_size, CTRL_ATTR_FAMILY_NAME, &value, &size) ||
            size != 8 || memcmp(value, "nl80211", 8)) { errno = EPROTO; return -1; }
    } else if (last_sequence == 2) {
        if (h->nlmsg_type != 42 || g->cmd != NL80211_CMD_GET_INTERFACE ||
            (h->nlmsg_flags & NLM_F_DUMP) != NLM_F_DUMP || attr_size) { errno = EPROTO; return -1; }
    } else if (last_sequence == 3) {
        if (h->nlmsg_type != 42 || g->cmd != NL80211_CMD_GET_REG ||
            plain_u32(attrs, attr_size, NL80211_ATTR_WIPHY, &identity) || identity != 7) { errno = EPROTO; return -1; }
    } else { errno = EPROTO; return -1; }
    if (!strcmp(scenario, "send-again")) { errno = EAGAIN; return -1; }
    return (ssize_t)length;
}
ssize_t fake_recvmsg(int fd, struct msghdr *message, int flags) {
    (void)flags;
    if (fd != 99) { errno = EPROTO; return -1; }
    if (!strcmp(scenario, "receive-again")) { errno = EAGAIN; return -1; }
    _Alignas(struct nlmsghdr) uint8_t packet[2048];
    uint16_t family = 42;
    uint32_t index = 11, phy = 7, role = NL80211_IFTYPE_STATION;
    uint8_t command = last_sequence == 1 ? CTRL_CMD_NEWFAMILY :
                      last_sequence == 2 ? NL80211_CMD_NEW_INTERFACE : NL80211_CMD_GET_REG;
    init_request(packet, last_sequence == 1 ? GENL_ID_CTRL : family, command, last_sequence);
    struct nlmsghdr *h = (struct nlmsghdr *)packet;
    h->nlmsg_flags = 0;
    if (last_sequence == 1) {
        if (!strcmp(scenario, "invalid-family")) family = GENL_MIN_ID - 1;
        add_attr(packet, sizeof(packet), CTRL_ATTR_FAMILY_ID, &family, sizeof(family));
        add_attr(packet, sizeof(packet), CTRL_ATTR_FAMILY_NAME,
                 !strcmp(scenario, "wrong-family-name") ? "foreign" : "nl80211", 8);
    } else if (last_sequence == 2) {
        if (!strcmp(scenario, "zero-index")) index = 0;
        if (!strcmp(scenario, "wrong-role")) role = NL80211_IFTYPE_AP;
        add_attr(packet, sizeof(packet), NL80211_ATTR_IFINDEX, &index, sizeof(index));
        add_attr(packet, sizeof(packet), NL80211_ATTR_IFNAME,
                 !strcmp(scenario, "missing-interface") ? "p2p00" : "wlan0",
                 !strcmp(scenario, "malformed-ifname") ? 5 : 6);
        add_attr(packet, sizeof(packet), NL80211_ATTR_IFTYPE, &role, sizeof(role));
        add_attr(packet, sizeof(packet), NL80211_ATTR_WIPHY, &phy, sizeof(phy));
        if (!strcmp(scenario, "dump-interrupted")) h->nlmsg_flags |= NLM_F_DUMP_INTR;
    } else {
        if (!strcmp(scenario, "foreign-wiphy")) phy++;
        if (strcmp(scenario, "global-regdom")) add_attr(packet, sizeof(packet), NL80211_ATTR_WIPHY, &phy, sizeof(phy));
        add_attr(packet, sizeof(packet), NL80211_ATTR_REG_ALPHA2, "US", 3);
        if (!strcmp(scenario, "kernel-error")) {
            struct nlmsgerr error = {.error = -EOPNOTSUPP};
            h->nlmsg_type = NLMSG_ERROR;
            h->nlmsg_len = NLMSG_LENGTH(sizeof(error));
            memcpy(NLMSG_DATA(h), &error, sizeof(error));
        }
    }
    if (!strcmp(scenario, "stale-sequence")) h->nlmsg_seq++;
    if (!strcmp(scenario, "wrong-command")) ((struct genlmsghdr *)NLMSG_DATA(h))->cmd++;
    size_t total = NLMSG_ALIGN(h->nlmsg_len);
    if (last_sequence == 2) {
        uint8_t record[512];
        if (!strcmp(scenario, "duplicate-interface") || !strcmp(scenario, "conflicting-interface")) {
            memcpy(packet + total, packet, h->nlmsg_len);
            if (!strcmp(scenario, "conflicting-interface")) {
                struct nlmsghdr *other = (struct nlmsghdr *)(packet + total);
                struct genlmsghdr *generic = NLMSG_DATA(other);
                const void *other_attrs = (const uint8_t *)generic + GENL_HDRLEN, *phy_value;
                size_t phy_length;
                if (find_plain_attr(other_attrs, other->nlmsg_len - NLMSG_HDRLEN - GENL_HDRLEN,
                                    NL80211_ATTR_WIPHY, &phy_value, &phy_length) || phy_length != 4) return -1;
                uint32_t other_phy = phy + 1;
                memcpy((void *)phy_value, &other_phy, sizeof(other_phy));
            }
            total += NLMSG_ALIGN(h->nlmsg_len);
        }
        /* Ignore an unrelated P2P interface and a non-netdev record. */
        init_request(record, family, NL80211_CMD_NEW_INTERFACE, last_sequence);
        ((struct nlmsghdr *)record)->nlmsg_flags = NLM_F_MULTI;
        uint32_t other_index = 22;
        add_attr(record, sizeof(record), NL80211_ATTR_IFINDEX, &other_index, sizeof(other_index));
        add_attr(record, sizeof(record), NL80211_ATTR_IFNAME, "p2p0", 5);
        add_attr(record, sizeof(record), NL80211_ATTR_IFTYPE, &role, sizeof(role));
        add_attr(record, sizeof(record), NL80211_ATTR_WIPHY, &phy, sizeof(phy));
        size_t record_size = ((struct nlmsghdr *)record)->nlmsg_len;
        memcpy(packet + total, record, record_size); total += NLMSG_ALIGN(record_size);
        init_request(record, family, NL80211_CMD_NEW_INTERFACE, last_sequence);
        ((struct nlmsghdr *)record)->nlmsg_flags = NLM_F_MULTI;
        add_attr(record, sizeof(record), NL80211_ATTR_WIPHY, &phy, sizeof(phy));
        record_size = ((struct nlmsghdr *)record)->nlmsg_len;
        memcpy(packet + total, record, record_size); total += NLMSG_ALIGN(record_size);
        struct nlmsghdr *done = (struct nlmsghdr *)(packet + total);
        memset(done, 0, NLMSG_SPACE(sizeof(int32_t)));
        done->nlmsg_type = NLMSG_DONE; done->nlmsg_seq = last_sequence;
        done->nlmsg_len = NLMSG_LENGTH(sizeof(int32_t));
        int32_t error = !strcmp(scenario, "dump-error") ? -EINTR : 0;
        memcpy(NLMSG_DATA(done), &error, sizeof(error));
        total += NLMSG_ALIGN(done->nlmsg_len);
    }
    if (message->msg_iovlen != 1 || message->msg_iov[0].iov_len < total) { errno = EMSGSIZE; return -1; }
    memcpy(message->msg_iov[0].iov_base, packet, total);
    struct sockaddr_nl *source = message->msg_name;
    memset(source, 0, sizeof(*source)); source->nl_family = AF_NETLINK;
    if (!strcmp(scenario, "foreign-sender")) source->nl_pid = 73;
    message->msg_namelen = sizeof(*source);
    message->msg_flags = !strcmp(scenario, "truncated-datagram") ? MSG_TRUNC : 0;
    return (ssize_t)total;
}
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    scenario = argv[1];
    struct wonder_regulatory output;
    memset(&output, 0x5a, sizeof(output));
    int rc = query_wlan_regulatory(&output), clear = 1;
    const uint8_t *raw = (const uint8_t *)&output;
    for (size_t i = 0; i < sizeof(output); i++) clear &= raw[i] == 0;
    printf("{\"rc\":%d,\"ifindex\":%u,\"wiphy\":%u,\"country\":\"%s\","
           "\"requests\":%d,\"socket_calls\":%d,\"closes\":%d,\"nonblocking\":%s,\"cleared\":%s}\n",
           rc, output.ifindex, output.wiphy, rc ? "" : output.alpha2, requests, socket_calls,
           closes, nonblocking ? "true" : "false", clear ? "true" : "false");
    return 0;
}
'''


class WlanRegulatoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="onyx-wlan-reg-review-")
        cls.root = Path(cls.temp.name)
        cls.before = {name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest()
                      for name in ("config.c", "wonder-cap-query.c", "wonder-cap-query.h")}
        stub = cls.root / "android"
        stub.mkdir()
        (stub / "log.h").write_text(
            "#define ANDROID_LOG_INFO 4\n#define ANDROID_LOG_ERROR 6\n"
            "int __android_log_print(int, const char *, const char *, ...);\n")
        for name, code in (("parser", PARSER_FIXTURE), ("wrapper", WRAPPER_FIXTURE), ("query", QUERY_FIXTURE)):
            source = cls.root / (name + ".c")
            source.write_text(code)
            command = ["cc", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror",
                       "-I", str(SOURCE), "-I", str(cls.root), str(source),
                       "-ldl", "-o", str(cls.root / name)]
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()
        after = {name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() for name in cls.before}
        if after != cls.before:
            raise AssertionError("Reviewed sources changed during the regression run")

    def case(self, binary, name):
        result = subprocess.run([str(self.root / binary), name], capture_output=True,
                                text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_matching_primary_sta_and_per_wiphy_country(self):
        interface = self.case("parser", "interface-valid")
        self.assertEqual((interface["rc"], interface["ifindex"], interface["wiphy"]), (0, 11, 7))
        country = self.case("parser", "reg-valid")
        self.assertEqual((country["rc"], country["ifindex"], country["wiphy"], country["country"]),
                         (0, 11, 7, "US"))

    def test_rejects_wrong_missing_ambiguous_or_malformed_interface(self):
        cases = ("wrong-index", "zero-expected", "missing-index", "wrong-name", "name-without-nul",
                 "wrong-role", "missing-role", "missing-wiphy", "duplicate-wiphy", "truncated", "flagged-wiphy")
        for name in cases:
            with self.subTest(name=name):
                self.assertLess(self.case("parser", "interface-" + name)["rc"], 0)

    def test_rejects_global_fallback_bad_country_and_ambiguous_wiphy(self):
        cases = ("wrong-wiphy", "missing-wiphy", "duplicate-wiphy", "lowercase", "world", "no-nul",
                 "long", "missing-country", "duplicate-country", "truncated", "flagged-country")
        for name in cases:
            with self.subTest(name=name):
                self.assertLess(self.case("parser", "reg-" + name)["rc"], 0)

    def test_wrapper_uses_verified_country_and_preserves_primary_channel_and_config(self):
        result = self.case("wrapper", "valid")
        self.assertTrue(result["returned"])
        self.assertEqual((result["query_calls"], result["start_calls"], result["country"]), (1, 1, "US"))
        self.assertEqual(result["original_country"], "TN")
        for key in ("channels_preserved", "args_preserved", "config_preserved", "hopping_extension"):
            self.assertTrue(result[key], key)

    def test_wrapper_failed_query_never_calls_native_start(self):
        result = self.case("wrapper", "query-failure")
        self.assertFalse(result["returned"])
        self.assertEqual((result["query_calls"], result["start_calls"], result["country"]), (1, 0, ""))

    def test_wrapper_invalid_input_never_queries_or_starts(self):
        for name in ("missing-original", "null-config", "oversize-config"):
            with self.subTest(name=name):
                result = self.case("wrapper", name)
                self.assertFalse(result["returned"])
                self.assertEqual((result["query_calls"], result["start_calls"]), (0, 0))

    def test_production_query_completes_interface_dump_then_queries_exact_wiphy(self):
        result = self.case("query", "valid")
        self.assertEqual((result["rc"], result["ifindex"], result["wiphy"], result["country"]), (0, 11, 7, "US"))
        self.assertEqual((result["requests"], result["socket_calls"], result["closes"]), (3, 1, 1))
        self.assertTrue(result["nonblocking"])

    def test_production_query_failures_are_bounded_and_clear_all_output(self):
        cases = ("missing-interface", "socket-denied", "bind-denied", "send-again", "receive-again",
                 "timeout", "foreign-wiphy", "global-regdom", "kernel-error", "stale-sequence",
                 "foreign-sender", "truncated-datagram", "wrong-family-name", "invalid-family",
                 "wrong-command", "zero-index", "wrong-role", "malformed-ifname",
                 "duplicate-interface", "conflicting-interface", "dump-interrupted", "dump-error")
        for name in cases:
            with self.subTest(name=name):
                result = self.case("query", name)
                self.assertLess(result["rc"], 0)
                self.assertTrue(result["cleared"])
                self.assertEqual(result["country"], "")
                self.assertLessEqual(result["requests"], 3)
                if name != "socket-denied":
                    self.assertEqual(result["closes"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
