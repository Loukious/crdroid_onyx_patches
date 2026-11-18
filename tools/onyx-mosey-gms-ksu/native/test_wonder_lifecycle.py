#!/usr/bin/env python3
"""Run real Wonder init/close functions with faulting kernel resource contracts.

This is an offline host harness. It cannot validate firmware, actual kernel
locking, SELinux, or driver interoperability. Mocks reject leaked ownership and
the parent/vdev operations that would make ndo_open/ndo_stop wait for themselves.
The actual adapter reference loop also runs after registration, with adjacent
flag sentinels and the historical out-of-bounds expression as a negative control.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

KERNEL = Path("/home/loukious/Android/custom-rom/kernel/platform/kernel-6.18/modules/qcacld-3.0/core/hdd/src")
SOURCE = Path(os.environ.get("WONDER_LIFECYCLE_SOURCE", str(KERNEL / "wlan_hdd_wonder.c")))
MAIN_SOURCE = Path(os.environ.get("WONDER_MAIN_SOURCE", str(KERNEL / "wlan_hdd_main.c")))
MAIN_HEADER = Path(os.environ.get("WONDER_MAIN_HEADER", str(KERNEL.parent / "inc" / "wlan_hdd_main.h")))


def extract_function(text, signature):
    start = re.search(signature, text).start()
    opening = text.index("{", start)
    tokens = re.compile(r'/\*[\s\S]*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{}]')
    depth = 0
    for token in tokens.finditer(text, opening):
        if token.group() == "{":
            depth += 1
        elif token.group() == "}":
            depth -= 1
            if not depth:
                return text[start:token.end()]
    raise ValueError("Unclosed production function")


def extract_reference_initialization(main, header):
    """Retain the real loop, enum and adjacent member order without rewriting C."""
    function = extract_function(main, r'struct hdd_adapter \*hdd_open_adapter\(')
    loop = re.search(r'for \(i = 0; i < NET_DEV_HOLD_ID_MAX; i\+\+\)\s*'
                     r'qdf_atomic_init\([\s\S]*?;', function)
    enum = re.search(r'typedef enum \{\s*NET_DEV_HOLD_ID_RESERVED[\s\S]*?'
                     r'\} wlan_net_dev_ref_dbgid;', header)
    members = re.search(r'qdf_atomic_t net_dev_hold_ref_count\[NET_DEV_HOLD_ID_MAX\];\s*'
                        r'bool delete_in_progress;\s*bool is_virtual_iface;', header)
    if not all((loop, enum, members)):
        raise ValueError("Production reference initializer or adjacent flags not found")
    return loop.group(), enum.group(), members.group()


HEADER = r'''
#define _GNU_SOURCE
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
typedef uint8_t u8;
typedef uint64_t u64;
typedef int QDF_STATUS;
#define GFP_KERNEL 0
#define ETH_ALEN 6
#define IFF_UP 1
#define QDF_MONITOR_FLAG_OTHER_BSS (1U << 4)
#define QDF_MONITOR_FLAG_STA_COEX (1U << 31)
#define DEVICE_IFACE_OPENED 0
#define SME_SESSION_OPENED 0
#define WONDER_PERF_MODE_MAX 3
#define HDD_WONDER_NETDEV "wondertap0"
#define HDD_WONDER_COEX_MAX_DWELL_NS 32000000
#define QDF_IS_STATUS_ERROR(value) ((value) != 0)
#define QDF_IS_STATUS_SUCCESS(value) ((value) == 0)
#define IS_ERR(value) ((uintptr_t)(value) >= (uintptr_t)-4095)
#define PTR_ERR(value) ((int)(intptr_t)(value))
#define ERR_PTR(value) ((void *)(intptr_t)(value))
#define WRITE_ONCE(destination, value) ((destination) = (value))
#define rcu_assign_pointer(destination, value) ((destination) = (value))
#define ASSERT_RTNL() ((void)0)
#define hdd_info(...) ((void)0)
#define hdd_err(...) ((void)0)
#define hdd_warn(...) ((void)0)
struct net_device { unsigned flags; };
struct hdd_link { unsigned long link_flags; };
struct hdd_context { void *psoc, *parent_dev, *wiphy; };
/* PRODUCTION_REFERENCE_ENUM */
typedef int qdf_atomic_t;
struct hdd_adapter {
    struct net_device *dev;
    struct hdd_link *deflink;
    struct hdd_context *hdd_ctx;
    unsigned long event_flags;
    bool sta_mon_coexist, wonder_owned;
    /* PRODUCTION_REFERENCE_MEMBERS */
    unsigned char reference_guard[4];
};
_Static_assert(sizeof(qdf_atomic_t) == 4, "Reviewed kernel atomic width");
_Static_assert(offsetof(struct hdd_adapter, delete_in_progress) ==
               offsetof(struct hdd_adapter, net_dev_hold_ref_count) +
               sizeof(((struct hdd_adapter *)0)->net_dev_hold_ref_count),
               "Reviewed counter/flag adjacency");
_Static_assert(offsetof(struct hdd_adapter, is_virtual_iface) ==
               offsetof(struct hdd_adapter, delete_in_progress) + 1,
               "Reviewed flag adjacency");
struct osif_psoc_sync { int unused; };
struct osif_vdev_sync { bool registered, transition; unsigned operations; };
struct wondertap_set_freq_params { unsigned freq, bandwidth; };
struct wondertap_fixed_tx_rate_params { unsigned bw; };
struct wondertap_init_params {
    u8 mac_addr[6], country_code[3];
    struct wondertap_set_freq_params channel;
    struct wondertap_fixed_tx_rate_params tx_rate;
    bool amsdu_enable, ampdu_enable, rate_adaptation_enable;
    unsigned perf_mode;
};
struct hdd_wonder_session {
    struct hdd_adapter *adapter;
    void *peer, *sched, *coex;
    struct wondertap_set_freq_params channel;
    struct wondertap_fixed_tx_rate_params tx_rate;
    bool airtime_enabled, suspended, failed;
};
struct hdd_wonder_provider { struct hdd_context *hdd_ctx; struct hdd_wonder_session *session; bool removing; };
struct hdd_adapter_create_param { bool is_add_virtual_iface; };
static struct hdd_wonder_provider *hdd_wonder_provider;
static struct hdd_wonder_session *hdd_wonder_active;
static bool hdd_wonder_standalone_active;
static int hdd_wonder_lock;
static const char *fault;
static unsigned parent_ops, admissions, setup_ops, transitions;
static unsigned sessions, adapters, peers, schedulers, syncs, radios;
static unsigned open_calls, close_calls, context_calls, violations, fallback_stops;
static uint32_t monitor_flags, flags_at_open, flags_at_cleanup;
static unsigned flag_sets, flag_clears;
static bool provider_locked, wiphy_locked;
static struct osif_vdev_sync *registered_sync;
static struct hdd_adapter *opened_adapter;
static struct osif_psoc_sync psoc_sync;
static struct hdd_context context;
static int bad(void) { violations++; return -EDEADLK; }
static bool failed(const char *name) { return !strcmp(fault, name); }
static void mutex_lock(void *lock) {
    if (lock == &hdd_wonder_lock) { if (provider_locked) bad(); provider_locked = true; }
    else { if (wiphy_locked) bad(); wiphy_locked = true; }
}
static void mutex_unlock(void *lock) {
    if (lock == &hdd_wonder_lock) { if (!provider_locked) bad(); provider_locked = false; }
    else { if (!wiphy_locked) bad(); wiphy_locked = false; }
}
static void wiphy_lock(void *phy) { mutex_lock(phy); }
static void wiphy_unlock(void *phy) { mutex_unlock(phy); }
static bool is_valid_ether_addr(const u8 *mac) { return !(mac[0] & 1) && !!memcmp(mac, "\0\0\0\0\0\0", 6); }
static void ether_addr_copy(u8 *out, const u8 *in) { memcpy(out, in, 6); }
static int hdd_wonder_validate_rate(const struct wondertap_fixed_tx_rate_params *rate) { (void)rate; return 0; }
static int hdd_wonder_bandwidth(unsigned bw) { return bw <= 2 ? (int)bw : -EINVAL; }
static int osif_psoc_sync_op_start(void *dev, struct osif_psoc_sync **out) { (void)dev; if (failed("psoc-operation")) return -EBUSY; parent_ops++; *out=&psoc_sync; return 0; }
static void osif_psoc_sync_op_stop(struct osif_psoc_sync *sync) { if (sync!=&psoc_sync || !parent_ops) bad(); else parent_ops--; }
static int wlan_hdd_validate_context(struct hdd_context *ctx) { (void)ctx; context_calls++; return failed("initial-context") ? -EIO : 0; }
static bool cds_is_driver_recovering(void) { return false; }
static bool cds_is_driver_unloading(void) { return false; }
static bool cds_is_driver_loaded(void) { return true; }
static int hdd_trigger_psoc_idle_restart(struct hdd_context *ctx) { (void)ctx; return 0; }
static bool hdd_wonder_can_start(struct hdd_context *ctx) { (void)ctx; return !failed("can-start"); }
static int ucfg_reg_get_current_country(void *psoc, u8 *country) { (void)psoc; memcpy(country,"US",3); return 0; }
static int init_net;
static struct net_device *dev_get_by_name(void *net, const char *name) { (void)net; (void)name; return NULL; }
static void dev_put(struct net_device *dev) { (void)dev; }
static void *kzalloc(size_t length, int mode) { (void)mode; if (failed("session-allocation")) return NULL; sessions++; return calloc(1,length); }
static void kfree(void *value) { if (value) { if (!sessions) bad(); else sessions--; free(value); } }
static int osif_vdev_sync_create_and_trans(void *dev, struct osif_vdev_sync **out) {
    (void)dev; if (failed("sync-create")) return -ENOMEM;
    *out=calloc(1,sizeof(**out)); (*out)->transition=true; syncs++; transitions++; return 0;
}
static void osif_vdev_sync_register(struct net_device *dev, struct osif_vdev_sync *sync) {
    (void)dev; if (!sync || registered_sync || sync->registered) bad();
    else { sync->registered=true; registered_sync=sync; }
}
static void osif_vdev_sync_trans_stop(struct osif_vdev_sync *sync) {
    if (!sync || !sync->transition || !transitions) bad();
    else { sync->transition=false; transitions--; }
}
static void osif_vdev_sync_destroy(struct osif_vdev_sync *sync) {
    if (!sync || sync->registered || sync->transition || sync->operations) bad();
    else { syncs--; free(sync); }
}
static bool wlan_mlme_sta_mon_admission_begin(void *psoc) { (void)psoc; if (failed("admission")) return false; admissions++; return true; }
static void wlan_mlme_sta_mon_admission_end(void *psoc) { (void)psoc; if (!admissions) bad(); else admissions--; }
static int wlan_cfg80211_register_netdevice(struct net_device *dev) { (void)dev; return failed("registration") ? -EINVAL : 0; }
static int register_netdevice(struct net_device *dev) { (void)dev; return 0; }
static void qdf_atomic_init(qdf_atomic_t *counter) {
    const int zero = 0;
    /* memcpy exposes writes into adjacent flag bytes in the historical loop. */
    memcpy(counter, &zero, sizeof(zero));
}
static void ucfg_dp_set_mon_conf_flags(void *psoc, uint32_t flags) {
    if (psoc != context.psoc) bad();
    if (flags) {
        uint32_t expected = QDF_MONITOR_FLAG_OTHER_BSS |
            (opened_adapter && opened_adapter->sta_mon_coexist ? QDF_MONITOR_FLAG_STA_COEX : 0);
        if (!opened_adapter || registered_sync || !transitions || admissions ||
            (opened_adapter->dev->flags & IFF_UP) || flags != expected || monitor_flags) bad();
        flag_sets++;
    } else {
        /* Native unbind/filter cleanup must finish before this reset. */
        if (opened_adapter || !wiphy_locked || registered_sync || setup_ops || !monitor_flags) bad();
        flag_clears++;
    }
    monitor_flags = flags;
}
'''

MOCKS = r'''
static int hdd_wonder_add_monitor(struct hdd_context *ctx, struct hdd_adapter **out, const char *name, u8 *mac) {
    (void)name; (void)mac;
    if (!wiphy_locked || !admissions || !transitions) return bad();
    if (failed("monitor-add")) return -EBUSY;
    struct hdd_adapter *adapter=calloc(1,sizeof(*adapter));
    adapter->dev=calloc(1,sizeof(*adapter->dev)); adapter->deflink=calloc(1,sizeof(*adapter->deflink));
    adapter->hdd_ctx=ctx; adapter->sta_mon_coexist=!failed("standalone-success");
    struct hdd_adapter_create_param create={.is_add_virtual_iface=true};
    int rc=hdd_register_netdevice(adapter,adapter->dev,&create);
    if (!rc) {
        hdd_adapter_reference_init(adapter);
        if (!adapter->is_virtual_iface) bad();
    }
    if (!rc && failed("add-after-registration")) {
        if (!adapter->is_virtual_iface) bad(); rc=-EBUSY;
    }
    if (rc) { free(adapter->deflink); free(adapter->dev); free(adapter); return rc; }
    adapters++; *out=adapter; opened_adapter=adapter; return 0;
}
static void *hdd_wonder_peer_create(struct hdd_adapter *adapter) { (void)adapter; if (failed("peer-create")) return ERR_PTR(-ENOMEM); peers++; return malloc(1); }
static int dev_open(struct net_device *dev, void *extack) {
    (void)extack; open_calls++;
    if (parent_ops || setup_ops || transitions || admissions || wiphy_locked || !registered_sync) return bad();
    flags_at_open=monitor_flags;
    if (!monitor_flags) return bad();
    if (failed("dev-open")) return -EAGAIN;
    dev->flags|=IFF_UP;
    struct hdd_adapter *adapter=hdd_wonder_provider->session->adapter;
    adapter->event_flags|=1; adapter->deflink->link_flags|=1;
    return 0;
}
static int osif_vdev_sync_op_start(struct net_device *dev, struct osif_vdev_sync **out) {
    (void)dev; if (parent_ops || !registered_sync || registered_sync->transition) return bad();
    if (failed("setup-operation")) return -EBUSY;
    *out=registered_sync; (*out)->operations++; setup_ops++; return 0;
}
static void osif_vdev_sync_op_stop(struct osif_vdev_sync *sync) {
    if (sync!=registered_sync || !sync->operations || !setup_ops) bad();
    else { sync->operations--; setup_ops--; }
}
static u64 ktime_get_ns(void) { return 1000000; }
static int hdd_wonder_set_channel(struct hdd_wonder_session *session, const struct wondertap_set_freq_params *params, u64 end, u64 duration, u64 *completed) {
    (void)end; (void)duration; if (!setup_ops || !wiphy_locked) return bad();
    if (failed("channel")) return -EOPNOTSUPP; session->channel=*params; *completed=ktime_get_ns(); return 0;
}
static int hdd_wonder_peer_validate_rate(void *peer, const struct wondertap_fixed_tx_rate_params *rate) { (void)peer; (void)rate; return failed("rate") ? -EINVAL : 0; }
static int hdd_wonder_sched_ops;
static void *hdd_wonder_sched_create(struct hdd_adapter *adapter, struct hdd_wonder_session *session, const void *ops) { (void)adapter; (void)session; (void)ops; if (failed("scheduler")) return ERR_PTR(-ENOMEM); schedulers++; return malloc(1); }
static int hdd_wonder_bind_clock(struct hdd_wonder_session *session, bool resume) { (void)session; (void)resume; return failed("clock") ? -EIO : 0; }
static int hdd_wonder_airtime(struct hdd_wonder_session *session, bool enabled) {
    if (enabled && failed("airtime")) return -EIO;
    if (enabled && !session->airtime_enabled) radios++;
    if (!enabled && session->airtime_enabled) radios--;
    session->airtime_enabled=enabled; return 0;
}
static void hdd_wonder_sched_note_channel(void *sched, unsigned freq, unsigned bw, u64 completed) { (void)sched; (void)freq; (void)bw; (void)completed; }
static bool hdd_is_any_interface_open(struct hdd_context *ctx) { (void)ctx; return true; }
static void hdd_psoc_idle_timer_start(struct hdd_context *ctx) { (void)ctx; }
static void wlan_mlme_sta_mon_update_begin(void *psoc) { (void)psoc; }
static void wlan_mlme_sta_mon_update_end(void *psoc) { (void)psoc; }
static void synchronize_rcu(void) { }
static void hdd_wonder_coex_destroy(void *coex) { (void)coex; }
static void hdd_wonder_sched_destroy(void *sched) { if (sched) { schedulers--; free(sched); } }
static void hdd_wonder_peer_destroy(void *peer) { if (peer) { peers--; free(peer); } }
static void netif_tx_disable(struct net_device *dev) { (void)dev; }
static void dev_close(struct net_device *dev) {
    close_calls++;
    if (parent_ops || setup_ops || transitions || wiphy_locked) { bad(); return; }
    dev->flags&=~IFF_UP;
    if (!failed("stop-rejected")) {
        opened_adapter->event_flags=0; opened_adapter->deflink->link_flags=0;
    }
}
static struct osif_vdev_sync *osif_vdev_sync_unregister(struct net_device *dev) {
    (void)dev; if (setup_ops || parent_ops) bad();
    struct osif_vdev_sync *sync=registered_sync;
    if (sync) { sync->registered=false; registered_sync=NULL; }
    return sync;
}
static void osif_vdev_sync_wait_for_ops(struct osif_vdev_sync *sync) { if (!sync || sync->operations || setup_ops) bad(); }
static bool test_bit(unsigned index, const unsigned long *bits) { return !!(*bits & (1UL<<index)); }
static void clear_bit(unsigned index, unsigned long *bits) { *bits &= ~(1UL<<index); }
static int hdd_stop_adapter(struct hdd_context *ctx, struct hdd_adapter *adapter) { (void)ctx; fallback_stops++; adapter->event_flags=0; adapter->deflink->link_flags=0; return 0; }
static void hdd_deinit_adapter(struct hdd_context *ctx, struct hdd_adapter *adapter, bool held) { (void)ctx; (void)adapter; (void)held; }
static void hdd_close_adapter(struct hdd_context *ctx, struct hdd_adapter *adapter, bool held) {
    (void)ctx; (void)held;
    if (!wiphy_locked || !adapter->is_virtual_iface || registered_sync || setup_ops || parent_ops || (adapter->dev->flags & IFF_UP)) bad();
    flags_at_cleanup=monitor_flags;
    if (monitor_flags != (QDF_MONITOR_FLAG_OTHER_BSS |
        (adapter->sta_mon_coexist ? QDF_MONITOR_FLAG_STA_COEX : 0))) bad();
    adapters--; free(adapter->deflink); free(adapter->dev); free(adapter); opened_adapter=NULL;
}
'''

DRIVER = r'''
int main(int argc, char **argv) {
    if (argc!=2) return 2;
    fault=argv[1]; context.psoc=(void *)1; context.parent_dev=(void *)2; context.wiphy=(void *)3;
    if (failed("reference-initialization")) {
        struct hdd_adapter adapter={.delete_in_progress=true, .is_virtual_iface=true,
                                    .reference_guard={0xa5,0x5a,0x3c,0xc3}};
        for (unsigned i=0; i<NET_DEV_HOLD_ID_MAX; i++) adapter.net_dev_hold_ref_count[i]=7;
        hdd_adapter_reference_init(&adapter);
        unsigned nonzero=0;
        for (unsigned i=0; i<NET_DEV_HOLD_ID_MAX; i++) nonzero+=!!adapter.net_dev_hold_ref_count[i];
        bool guard=adapter.reference_guard[0]==0xa5 && adapter.reference_guard[1]==0x5a &&
                   adapter.reference_guard[2]==0x3c && adapter.reference_guard[3]==0xc3;
        printf("{\"nonzero_counters\":%u,\"delete_in_progress\":%s,\"is_virtual_iface\":%s,\"guard\":%s}\n",
               nonzero,adapter.delete_in_progress?"true":"false",adapter.is_virtual_iface?"true":"false",guard?"true":"false");
        return 0;
    }
    struct hdd_wonder_provider provider={.hdd_ctx=&context}; hdd_wonder_provider=&provider;
    struct wondertap_init_params params={.mac_addr={2,1,2,3,4,5},.country_code={'U','S',0},.channel={2437,0},.tx_rate={0}};
    if (failed("country-mismatch")) memcpy(params.country_code,"TN",3);
    void *handle=(void *)0x1234;
    int rc=hdd_wonder_init(&handle,&params);
    unsigned retained=sessions+adapters+peers+schedulers+syncs+radios;
    bool handles=rc ? !handle && !provider.session && !hdd_wonder_active : handle==provider.session && handle==hdd_wonder_active;
    if (parent_ops || setup_ops || transitions || admissions || provider_locked || wiphy_locked) bad();
    if (!rc) {
        mutex_lock(&hdd_wonder_lock); hdd_wonder_close_session(&provider); mutex_unlock(&hdd_wonder_lock);
    }
    unsigned remaining=sessions+adapters+peers+schedulers+syncs+radios;
    printf("{\"rc\":%d,\"violations\":%u,\"retained\":%u,\"remaining\":%u,\"handles\":%s,\"opens\":%u,\"closes\":%u,\"fallback_stops\":%u,\"parent_ops\":%u,\"setup_ops\":%u,\"transitions\":%u,\"admissions\":%u,\"monitor_flags\":%u,\"flags_at_open\":%u,\"flags_at_cleanup\":%u,\"flag_sets\":%u,\"flag_clears\":%u}\n",rc,violations,retained,remaining,handles?"true":"false",open_calls,close_calls,fallback_stops,parent_ops,setup_ops,transitions,admissions,monitor_flags,flags_at_open,flags_at_cleanup,flag_sets,flag_clears);
    return 0;
}
'''


class WonderLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="onyx-wonder-lifecycle-")
        cls.path = Path(cls.temp.name)
        cls.before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (SOURCE, MAIN_SOURCE, MAIN_HEADER)}
        source = SOURCE.read_text()
        main = MAIN_SOURCE.read_text()
        loop, enum, members = extract_reference_initialization(main, MAIN_HEADER.read_text())
        register = extract_function(main, r'static int\s+hdd_register_netdevice\(')
        close = extract_function(source, r'static void hdd_wonder_close_session\(')
        start = extract_function(source, r'static int hdd_wonder_init\(')
        header = HEADER.replace("/* PRODUCTION_REFERENCE_ENUM */", enum).replace(
            "/* PRODUCTION_REFERENCE_MEMBERS */", members)
        initializer = "static void hdd_adapter_reference_init(struct hdd_adapter *adapter) {\nuint32_t i;\n" + loop + "\n}\n"
        code = header + register + initializer + MOCKS + close + start + DRIVER
        (cls.path / "harness.c").write_text(code)
        result = subprocess.run(["cc", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror",
                                 "-Wno-misleading-indentation", str(cls.path / "harness.c"),
                                 "-o", str(cls.path / "harness")], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        # Retain the original out-of-bounds expression as a negative control.
        # This changes only generated harness text, never production sources.
        historical_loop = loop.replace("net_dev_hold_ref_count[i]", "net_dev_hold_ref_count[NET_DEV_HOLD_ID_MAX]")
        bad_initializer = initializer.replace(loop, historical_loop)
        bad_code = header + register + bad_initializer + MOCKS + close + start + DRIVER
        (cls.path / "reference-regression.c").write_text(bad_code)
        result = subprocess.run(["cc", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror",
                                 "-Wno-misleading-indentation", str(cls.path / "reference-regression.c"),
                                 "-o", str(cls.path / "reference-regression")], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)

    @classmethod
    def tearDownClass(cls):
        after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in cls.before}
        cls.temp.cleanup()
        if cls.before != after:
            raise AssertionError("Production lifecycle sources changed during tests")

    def case(self, name):
        result = subprocess.run([str(self.path / "harness"), name], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["violations"], 0, output)
        self.assertEqual(output["remaining"], 0, output)
        self.assertTrue(output["handles"], output)
        for key in ("parent_ops", "setup_ops", "transitions", "admissions"):
            self.assertEqual(output[key], 0, output)
        self.assertEqual(output["monitor_flags"], 0, output)
        self.assertEqual(output["flag_sets"], output["flag_clears"], output)
        return output

    def test_success_retains_resources_until_teardown(self):
        result = self.case("success")
        self.assertEqual(result["rc"], 0)
        self.assertEqual(result["retained"], 6)
        self.assertEqual((result["opens"], result["closes"]), (1, 1))
        self.assertEqual(result["fallback_stops"], 0)
        self.assertEqual((result["flag_sets"], result["flag_clears"]), (1, 1))
        self.assertEqual((result["flags_at_open"], result["flags_at_cleanup"]),
                         ((1 << 31) | (1 << 4), (1 << 31) | (1 << 4)))

    def test_standalone_monitor_does_not_receive_sta_admission_flag(self):
        result = self.case("standalone-success")
        self.assertEqual(result["rc"], 0)
        self.assertEqual((result["flag_sets"], result["flag_clears"]), (1, 1))
        self.assertEqual((result["flags_at_open"], result["flags_at_cleanup"]), (1 << 4, 1 << 4))

    def reference_case(self, executable):
        result = subprocess.run([str(self.path / executable), "reference-initialization"],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_reference_initialization_preserves_adjacent_flags(self):
        self.assertEqual(self.reference_case("harness"), {
            "nonzero_counters": 0, "delete_in_progress": True,
            "is_virtual_iface": True, "guard": True})

    def test_historical_reference_loop_is_detected(self):
        result = self.reference_case("reference-regression")
        self.assertGreater(result["nonzero_counters"], 0, result)
        self.assertFalse(result["delete_in_progress"], result)
        self.assertFalse(result["is_virtual_iface"], result)
        self.assertFalse(result["guard"], result)

    def test_early_rejections_acquire_no_monitor(self):
        for fault in ("psoc-operation", "initial-context", "can-start", "country-mismatch", "session-allocation", "sync-create", "admission", "monitor-add", "registration", "add-after-registration"):
            with self.subTest(fault=fault):
                result = self.case(fault)
                self.assertLess(result["rc"], 0)
                self.assertEqual((result["retained"], result["opens"], result["closes"]), (0, 0, 0))

    def test_registered_unopened_monitor_is_freed(self):
        result = self.case("peer-create")
        self.assertLess(result["rc"], 0)
        self.assertEqual((result["retained"], result["opens"], result["closes"]), (0, 0, 0))
        result = self.case("dev-open")
        self.assertLess(result["rc"], 0)
        self.assertEqual((result["retained"], result["opens"], result["closes"]), (0, 1, 0))

    def test_each_post_open_failure_releases_guards_before_ndo_stop(self):
        for fault in ("setup-operation", "channel", "rate", "scheduler", "clock", "airtime"):
            with self.subTest(fault=fault):
                result = self.case(fault)
                self.assertLess(result["rc"], 0)
                self.assertEqual((result["retained"], result["opens"], result["closes"]), (0, 1, 1))

    def test_rejected_ndo_stop_still_cleans_session_and_sync(self):
        result = self.case("stop-rejected")
        self.assertEqual(result["rc"], 0)
        self.assertEqual(result["fallback_stops"], 1)
        self.assertEqual((result["opens"], result["closes"]), (1, 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
