# Onyx native Mosey integration

`vendor/extra/product.mk` inherits this product fragment, which directly inherits
`vendor/gms-mosey/mosey/mosey-vendor.mk`. Android evaluates product inheritance
as a graph, so a variable set in this fragment cannot enable an earlier parent
conditional reliably. The direct include packages the existing Google native service, FFI,
framework VINTF declaration, and sysconfig files. The APK, GMS, and native blobs
are retained. `BoardConfigExtra.mk` adds the small private policy extension.

`onyx-mosey.rc` overrides the bundled service after `mosey.rc` in Android init's
sorted directory parsing. The bundled `on boot` action starts the replacement
service. It starts the source-built `onyx_mosey_launcher` with the existing
`mosey_server_exec` label, system UID, network groups and capabilities. Init
performs the normal secure transition into `mosey_server`. The launcher sets
`LD_PRELOAD` and `KONOHA_MOSEY_WONDER=1`, then executes the unchanged Google daemon
within the same domain. The environment applies only to that process.

Setting `LD_PRELOAD` directly in init cannot work: the domain transition sets
`AT_SECURE`, and Bionic ignores that environment variable. The same-domain second
exec does not elevate privileges: both executables have ordinary file modes and
no file capabilities, UID/groups remain unchanged, and init's ambient
`NET_ADMIN`/`NET_RAW` capabilities survive. The policy adds only
`mosey_server_exec:file execute_no_trans` for that second exec. It does not grant
`noatsecure` or change enforcement. This path has been inspected statically;
Runtime validation on Onyx confirmed the same domain, UID/capabilities, and
process-local preload with SELinux Enforcing.

The library intercepts dynamic resolution of `mosey_start_5`. It selects radio
2, the FFI's `wonder0`/`wonder` backend, and appends protobuf field 5 = true to
enable the protocol's channel rotation. All other start arguments and protobuf
fields are preserved, including the app's requested channels, country code,
aggregation, and rate adaptation. Other dynamically resolved symbols pass
through unchanged. The FFI parses the protobuf synchronously before returning,
so the extended buffer is freed after the call.

## Current binary contract

The inspected FFI is
`vendor/gms-mosey/mosey/lib64/libmosey_daemon_ffi.so`, SHA-256
`7de30b96a0a413eb6348860e76fb2032edf7f350658857bea3c2862b666dd9e7`.
All addresses below are ELF virtual addresses from static inspection.

| Contract | Evidence |
| --- | --- |
| Start ABI: channels/count, max mDNS, country, radio, config/length | `mosey_start_5` at `0x15c33c` saves registers x0–x6 |
| Radio 1 = `radiotap0`; radio 2 = `wonder0`/`wonder` | Validation `0x15c444`; selector `0x152d94`; builders `0x1c6aac` and `0x1c6a6c` |
| Config field 1 = DBS; 2 = STA frequency; 3 = daemon AMSDU; 4 = driver AMPDU; 5 = channel hopping; 6 = rate adaptation; 7 = maximum AMSDU size mode | Start's logged accessors `0x15c5c0`; getters `0x25d6e4`–`0x25d714`; serializer `0x25d870` |
| Config field 5 bool uses tag `0x28` | Serializer `0x25d914`–`0x25d934`, accessor `0x245d0c` → `0x25d704` |
| GET_CAP consumes MTU u32, hardware AMSDU u8, hardware AMPDU u8 | Parser `0x1c8514`–`0x1c874c` |
| Fixed rate has HT/20 MHz or VHT/80 MHz, 0.8 us GI, configured NSS and MCS | Attribute builder `0x1c8450`; u32 helper `0x1c025c`; bandwidth helper `0x1c0304` hardcodes attribute 2 |
| Native vendor commands: frequency, filter, fixed rate, country, MAC, capabilities | Sender `0x14acb4`, direct callers and shared tail helper `0x15f138` emit subcommands 1–5 and 8 |

The current native service is Binder V2 and supports transactions 1–3 plus
interface hash/version. Its original dispatch at `0x825e0` rejects transaction 4.
The installed APK version 60715 (1.0.980159239), SHA-256
`7ab2deaea6c9c2bdd5ba0f935d6143c115f5ceb11cb8b63066496ad27a28da49`,
uses that transaction to obtain `MoseyHardwareCapability`. APK method `byt.i`
uses the hardware hopping result to decide whether to retain its current STA
association. When hopping is false, it disables autojoin and disconnects if the
requested channel shares the STA's band or Android DBS is unsupported. Normal
stop enables autojoin and reconnects its saved network through the app's existing
restore policy. The driver supports the resulting idle, unassociated STA state.

`wonder-capability-bridge.c` intercepts `AIBinder_Class_define` only for the exact
Mosey descriptor when the launcher enables the Wonder environment. Transaction 4
uses `wonder-cap-query.c` to resolve the exact `wonder` wiphy through a complete,
bounded nl80211 dump and issue the existing read-only GET_CAP vendor command.
It validates the real attribute 4 but returns protobuf field 1 = false in the
stable Parcelable for this Onyx profile. The frozen driver supports shared
traffic on the exact STA home channel; its vendor hopping flag does not establish
concurrent traffic on another channel. This controller capability is separate
from native config field 5, which remains true for software channel retuning.
Android DBS and Wonder HBS remain independent. Query errors fail the transaction.
All other calls retain the original handler, descriptor, lifetime handlers,
version, and hash.

The earlier bridge's Java decoding verified the original interface version
2/hash and a 12-byte stable Parcelable with hopping=true. The current bridge
preserves that parcel format and reports false while logging the real driver
result and the controller result separately. The query runs in
`mosey_server` with SELinux Enforcing and adds no sysfs or netlink permission.
A former sysfs-index implementation was rejected by SELinux and is not used.

The exact app flag and country-map override are maintained in the optional
`tools/onyx-mosey-gms-ksu` module. For the 2.4 GHz USB peer, the app selects channel
6. With DBS unsupported, the controller can release an existing connection and
start the AP-free native monitor on that channel. Shared STA operation remains
limited to its exact home channel, and the foreign-channel guards remain active.

## Kernel dependency and limits

This product requires the source-built Wonder module and the Onyx QCACLD
provider. The kernel port's generated module layout and dependency files own
loading. Its vendor module options enable the existing STA/AP/monitor
coexistence paths; init does not unload, reload, or reconfigure WLAN modules.

The original targeted Soong build of `onyx_mosey_launcher` and
`libmosey_onyx_config` passed. The capability update additionally compiled with
Android NDK 28.2, passed 16 KiB LOAD alignment checks, and was tested using a
reversible library bind followed by a native service restart. The library exports
only `dlsym` and `AIBinder_Class_define`. Current update evidence is retained in
`mosey-activation-fix-20261117T161143423932Z/goal-working-20261117/native-capability-integration`.
This source integration is reproduced by the patches repository's source overlay.
Portable actual-source Binder fixtures are maintained in
`tools/onyx-mosey-gms-ksu/native/test_wonder_capability_bridge.py`. They exercise
the stable parcel, fresh queries, query and parcel errors, original forwarding,
and exact descriptor/environment activation under strict GCC and ASan/UBSan.

This FFI rotates channels through SET_FREQUENCY. Static inspection of its
command sender did not find the newer schedule, TSF, station, or feature
commands. It does not submit NOP/STA schedule roles. Normal off-channel AWDL STA
coexistence remains unsupported; the shipping module options leave the explicit
STA probe disabled. The controller handoff uses the existing AP-free monitor
path instead. Tests on additional AWDL channels, ordinary social-channel hopping,
and an actual iPhone remain separate radio validation work.
