/* Host regression for the production monitor callback and AF_PACKET branch. */
#include <arpa/inet.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>

static unsigned assertions, publications;
#define CHECK(c) do { assertions++; if (!(c)) { \
    fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #c); exit(1); \
} } while (0)
#define DEBUG_NET_WARN_ON_ONCE(c) ((void)(c))
#define ETH_P_802_2 0x0004
#define PACKET_OUTGOING 4
#define QDF_STATUS_SUCCESS 0
#define QDF_STATUS_E_FAILURE 1
#define QDF_IS_STATUS_SUCCESS(value) ((value) == QDF_STATUS_SUCCESS)
#define dp_err_rl(...) ((void)0)
typedef int QDF_STATUS;
struct net_device { bool owned, ready, has_header; };
struct sk_buff {
    struct sk_buff *next;
    struct net_device *dev;
    unsigned char *head, *data;
    uint32_t len, tail, end;
    uint16_t mac_header, network_header, protocol;
    uint8_t pkt_type;
    bool released, freed;
    /* Oversized physical allocation keeps the unset-header pointer in-bounds
     * while end still models the crash's actual logical allocation limit.
     */
    unsigned char storage[66048], fragment[512];
};
typedef struct sk_buff *qdf_nbuf_t;
/* INSERT_PUSH_ENUM */
struct dp_tx_rx_stats {
    struct { unsigned rx_packets, rx_delivered, rx_refused; } per_cpu[4];
};
struct wlan_dp_psoc_context {
    struct { QDF_STATUS (*dp_nbuf_push_pkt)(qdf_nbuf_t, enum dp_nbuf_push_type); } dp_ops;
};
struct wlan_dp_intf {
    struct wlan_dp_psoc_context *dp_ctx;
    struct net_device *dev;
    struct { struct dp_tx_rx_stats tx_rx_stats; } dp_stats;
    struct { uint64_t rx_pkts, rx_bytes; } stats;
};
struct wlan_dp_link { struct wlan_dp_intf *dp_intf; };
struct sock { int sk_type; };
static bool atomic_context, refuse_push;
static enum dp_nbuf_push_type seen_types[8];
static struct sk_buff *seen_packets[8];
static unsigned seen_count;
static int32_t last_capture_put;

/* Actual common-kernel header helpers and QDF protocol assignment. */
/* INSERT_HEADER_HELPERS */
#define qdf_nbuf_set_protocol __qdf_nbuf_set_protocol
static bool dev_has_header(struct net_device *dev) { return dev->has_header; }

/* Guard the real AF_PACKET expression before its unsafe pointer mutation.
 * Report exactly the signed quantities skb_under_panic would print.
 */
static void *skb_push(struct sk_buff *skb, unsigned int len)
{
    last_capture_put = (int32_t)len;
    if (len > (uintptr_t)(skb->data - skb->head)) {
        fprintf(stderr, "AF_PACKET_UNDERFLOW put=%d len=%d data_offset=%td mac_header=%u tail=%u end=%u\n",
                (int32_t)len, (int32_t)(skb->len + len), skb->data - skb->head,
                skb->mac_header, skb->tail, skb->end);
        exit(42);
    }
    skb->data -= len;
    skb->len += len;
    return skb->data;
}
static void *skb_pull(struct sk_buff *skb, unsigned int len)
{
    CHECK(len <= skb->len && len <= skb->tail - (skb->data - skb->head));
    skb->data += len;
    skb->len -= len;
    return skb->data;
}
static void capture_adjust(struct sk_buff *skb, struct net_device *dev,
                           struct sock *sk)
{
    /* INSERT_CAPTURE_BRANCH */
}
static struct sk_buff *qdf_nbuf_next(struct sk_buff *skb) { return skb->next; }
static void qdf_nbuf_set_next(struct sk_buff *skb, struct sk_buff *next) { skb->next = next; }
static void qdf_nbuf_set_dev(struct sk_buff *skb, struct net_device *dev) { skb->dev = dev; }
static void qdf_nbuf_free(struct sk_buff *skb) { skb->freed = true; }
static unsigned qdf_nbuf_len(struct sk_buff *skb) { return skb->len; }
static unsigned qdf_get_cpu(void) { return 2; }
static bool qdf_in_atomic(void) { return atomic_context; }
#define qdf_net_stats_add_rx_pkts(stats, n) ((stats)->rx_pkts += (n))
#define qdf_net_stats_add_rx_bytes(stats, n) ((stats)->rx_bytes += (n))
static void qdf_net_buf_debug_release_skb(struct sk_buff *skb) { skb->released = true; }
#ifdef FEATURE_WLAN_WONDER
static bool hdd_wonder_netdev_transport_ready(struct net_device *dev) { return dev->ready; }
static bool hdd_wonder_netdev_is_owned(struct net_device *dev) { return dev->owned; }
#endif

/* INSERT_CALLBACK */

static QDF_STATUS push_packet(struct sk_buff *skb, enum dp_nbuf_push_type type)
{
    unsigned char *data = skb->data;
    unsigned char saved[66048], fragment[512];
    uint32_t len = skb->len, tail = skb->tail, end = skb->end;
    struct sock sk = { .sk_type = SOCK_RAW };
    CHECK(skb->released && !skb->freed);
    memcpy(saved, skb->storage, sizeof(saved));
    memcpy(fragment, skb->fragment, sizeof(fragment));
    /* Execute the same production RAW-capture branch before metadata checks:
     * the unchanged production callback must fail here with the exact panic.
     */
    capture_adjust(skb, skb->dev, &sk);
    CHECK(last_capture_put == 0);
    CHECK(skb->mac_header == skb->data - skb->head);
    CHECK(skb->protocol == htons(ETH_P_802_2));
    CHECK(skb->data == data && skb->len == len && skb->tail == tail && skb->end == end);
    CHECK(memcmp(saved, skb->storage, sizeof(saved)) == 0);
    CHECK(memcmp(fragment, skb->fragment, sizeof(fragment)) == 0);
    CHECK(seen_count < 8);
    seen_types[seen_count] = type;
    seen_packets[seen_count++] = skb;
    publications++;
    return refuse_push ? QDF_STATUS_E_FAILURE : QDF_STATUS_SUCCESS;
}

static struct sk_buff packets[3];
static void initialize_packet(struct sk_buff *skb, unsigned offset, unsigned initial_mac)
{
    memset(skb, 0, sizeof(*skb));
    for (unsigned i = 0; i < sizeof(skb->storage); i++)
        skb->storage[i] = (unsigned char)(i * 37 + 11);
    for (unsigned i = 0; i < sizeof(skb->fragment); i++)
        skb->fragment[i] = (unsigned char)(i * 19 + 7);
    skb->head = skb->storage;
    skb->data = skb->head + offset;
    skb->len = 395;
    skb->tail = offset + 74;
    skb->end = offset == 206 ? 384 : offset + 128;
    skb->mac_header = initial_mac;
    skb->network_header = offset;
    skb->protocol = htons(0x0800);
    skb->pkt_type = 3;
}
static void run_case(bool owned, bool atomic, unsigned count, unsigned offset,
                     unsigned initial_mac, bool refuse)
{
    struct net_device dev = { .owned = owned, .ready = true, .has_header = true };
    struct wlan_dp_psoc_context ctx = { .dp_ops.dp_nbuf_push_pkt = push_packet };
    struct wlan_dp_intf intf = { .dp_ctx = &ctx, .dev = &dev };
    struct wlan_dp_link link = { .dp_intf = &intf };
    unsigned char saved[3][66048], fragments[3][512];
    seen_count = 0;
    atomic_context = atomic;
    refuse_push = refuse;
    for (unsigned i = 0; i < count; i++) {
        initialize_packet(&packets[i], offset + i, initial_mac);
        packets[i].next = i + 1 < count ? &packets[i + 1] : NULL;
        memcpy(saved[i], packets[i].storage, sizeof(saved[i]));
        memcpy(fragments[i], packets[i].fragment, sizeof(fragments[i]));
    }
    CHECK(dp_mon_rx_packet_cbk(&link, &packets[0]) == QDF_STATUS_SUCCESS);
    CHECK(seen_count == count);
    CHECK(intf.dp_stats.tx_rx_stats.per_cpu[2].rx_packets == count);
    CHECK(intf.dp_stats.tx_rx_stats.per_cpu[2].rx_delivered == (refuse ? 0 : count));
    CHECK(intf.dp_stats.tx_rx_stats.per_cpu[2].rx_refused == (refuse ? count : 0));
    CHECK(intf.stats.rx_pkts == count && intf.stats.rx_bytes == count * 395);
    for (unsigned i = 0; i < count; i++) {
        enum dp_nbuf_push_type expected = i + 1 < count ? DP_NBUF_PUSH_SIMPLE :
            (atomic ? DP_NBUF_PUSH_NAPI : DP_NBUF_PUSH_BH_DISABLE);
#ifdef FEATURE_WLAN_WONDER
        if (owned)
            expected = DP_NBUF_PUSH_SIMPLE;
#endif
        CHECK(seen_packets[i] == &packets[i] && seen_types[i] == expected);
        CHECK(packets[i].dev == &dev && packets[i].pkt_type == 3);
        CHECK(packets[i].next == (i + 1 < count ? &packets[i + 1] : NULL));
        CHECK(packets[i].len == 395 && packets[i].tail == offset + i + 74);
        CHECK(memcmp(saved[i], packets[i].storage, sizeof(saved[i])) == 0);
        CHECK(memcmp(fragments[i], packets[i].fragment, sizeof(fragments[i])) == 0);
    }
}
static void check_rejected(void)
{
    struct net_device dev = { .owned = true, .ready = false, .has_header = true };
    struct wlan_dp_psoc_context ctx = { .dp_ops.dp_nbuf_push_pkt = push_packet };
    struct wlan_dp_intf intf = { .dp_ctx = &ctx, .dev = &dev };
    struct wlan_dp_link link = { .dp_intf = &intf };
    CHECK(dp_mon_rx_packet_cbk(NULL, &packets[0]) == QDF_STATUS_E_FAILURE);
    CHECK(dp_mon_rx_packet_cbk(&link, NULL) == QDF_STATUS_E_FAILURE);
    struct wlan_dp_link bad_link = { 0 };
    CHECK(dp_mon_rx_packet_cbk(&bad_link, &packets[0]) == QDF_STATUS_E_FAILURE);
#ifdef FEATURE_WLAN_WONDER
    seen_count = 0;
    initialize_packet(&packets[0], 206, UINT16_MAX);
    initialize_packet(&packets[1], 207, UINT16_MAX);
    packets[0].next = &packets[1];
    CHECK(dp_mon_rx_packet_cbk(&link, &packets[0]) == QDF_STATUS_SUCCESS);
    CHECK(seen_count == 0);
    CHECK(packets[0].freed && packets[1].freed);
    CHECK(!packets[0].next && !packets[1].next);
    CHECK(!packets[0].released && !packets[1].released);
    CHECK(packets[0].mac_header == UINT16_MAX && packets[1].mac_header == UINT16_MAX);
    CHECK(intf.dp_stats.tx_rx_stats.per_cpu[2].rx_refused == 2);
    CHECK(intf.stats.rx_pkts == 0 && intf.stats.rx_bytes == 0);
#endif
}
int main(void)
{
    /* First case reproduces both fresh boot records before the fix:
     * 206 - 65535 = -65329; 395 + (-65329) = -64934.
     */
    run_case(true, true, 1, 206, UINT16_MAX, false);
    const unsigned offsets[] = { 0, 64, 206, 512 };
    const unsigned initial_headers[] = { UINT16_MAX, 0, 32, 512 };
    for (unsigned owned = 0; owned < 2; owned++)
        for (unsigned atomic = 0; atomic < 2; atomic++)
            for (unsigned count = 1; count <= 3; count++)
                for (unsigned i = 0; i < 4; i++)
                    for (unsigned refuse = 0; refuse < 2; refuse++)
                        run_case(owned, atomic, count, offsets[i], initial_headers[i], refuse);
    check_rejected();
    printf("{\"assertions\":%u,\"publications\":%u}\n", assertions, publications);
    return 0;
}
