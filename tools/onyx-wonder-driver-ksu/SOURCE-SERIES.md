# Reviewed Onyx Wonder source series

Driver **v15** adds native AWDL multicast through the existing WMI raw transmit
command on the established exclusive channel. The current package is
`out/onyx-wonder-driver-20261118-v15.zip`, SHA-256
`77a918d755b4248fb06d6c25130cbf424338b3df7d0451cfe88ca51ff8b7e7d8`.
Its QCA payload SHA-256 is
`3b2e60fd74a61cb931f2d79c16658b3d551cf2f5bc82df5fe642c0cfd2f8dc51`.

The eighth patch, `0008-wonder-native-awdl-multicast.patch`, changes only
`qcacld-3.0/core/hdd/src/wlan_hdd_wonder.c` and
`qcacld-3.0/core/wma/src/wma_data.c` relative to v12. The manifest is
`source-series-v15.json`. All eight patches replay with zero fuzz and verify
**12 source files**, including the newly enumerated WMA source, against the
final build. The prior manifests and seven patches are preserved.

```sh
python3 verify-source-series.py --baseline /path/to/exact/accepted/modules \
  --manifest source-series-v15.json
```

The retained `wonder-native-multicast-v15-20261118/source-replay-receipt.json`
binds the manifest, patch identities, candidate source hashes and exact module
payload. Replay used a private temporary fixture containing the original frozen
baseline files plus the unchanged WMA file from the retained scan-lease source.
Every input matched the accepted artifact's original source manifest. The older
`durable-driver-export/baseline/` fixture omits WMA and cannot by itself replay
v15. The new receipt preserves the superseded draft export identities.

Native group transmission lets firmware assign the outer 802.11 sequence number;
original packet addresses and the AWDL sequence remain intact. The default route
retains helper/channel ownership and DMA completion checks. It reserves each
16-bit WMI descriptor ID before accepting packet ownership and never recycles
IDs during the module lifetime. The 65,535-reservation limit rejects admission
synchronously and preserves v12 mDNS peer delivery as a fallback. Other group
traffic may fail once this budget is exhausted. Extracted production-function
ASan/UBSan tests passed for reservation, rejection ownership and fallback; they
mock dependencies and do not establish hardware exhaustion behavior.

The installed v15 build passed ordinary and QoS group probes over the channel 6
radio. A subsequent stock Owly discovery trial captured six native phone
AirDrop mDNS frames at `33:33:00:00:00:fb`, verified a 208,896-byte file against
the source SHA-256, and restored ordinary Wi-Fi after close. These hardware
receipts are separate from source replay; see [the package README](README.md).
The first unsuccessful transfer remains retained. Validation does not cover
5 GHz, full channel hopping, simultaneous STA/AWDL service, MLO, long-duration
stability or iPhone interoperability.

## Earlier series through v12

Driver v12 adds `0007-wonder-awdl-mdns-peer-tx.patch` to the original six-patch
series. The seventh patch uses recently received AWDL synchronization frames to
identify peers for IPv6 mDNS delivery. The manifest is `source-series-v12.json`.
The complete seven-patch series replays with zero fuzz and verifies all 11
source files against the hashes used for the v12 build.

```sh
python3 verify-source-series.py --baseline /path/to/exact/accepted/modules \
  --manifest source-series-v12.json
```

## Original series through v9

The six patches reproduce all 11 changed or newly added source files of the
reviewed v9 QCA module, including the earlier receive-header correction. The
baseline is the source recorded for the installed artifact
`20261117T143428209411Z`, with QCA payload SHA256
`0a2eba04b57ccdc0ae9e57258b91b38440e4b983fa9e151fe5acf36a3d915969`.
The resulting reviewed v9 payload has SHA256
`54cf09f0dc27ac41eb9ce1cdc4bd4b5046d374520b4d773330d3a1a580b0b1d7`.

Run from the **modules root**, whose direct children include `qcacld-3.0/`
and `qca-wifi-host-cmn/`. The existing third patch retains its historical
`modules/` prefix, so its strip level differs:

| Patch | Strip level | Change |
| --- | --- | --- |
| `0001-wonder-monitor-lifecycle.patch` | `-p1` | Monitor registration, reference initialization and synchronization |
| `0002-wonder-monitor-rx-header.patch` | `-p1` | Receive header normalization |
| `0003-wonder-session-scan-lease.patch` | `-p2` | Session and scanner ownership |
| `0004-wonder-compact-awdl-rx.patch` | `-p1` | Compact shared-ring AWDL receive path |
| `0005-wonder-apfree-native-and-peer-rates.patch` | `-p1` | Unassociated STA lease, native startup/cleanup, pre-vdev channel validation and destination-compatible transmit rates |
| `0006-wonder-compact-unknown-raw-rx.patch` | `-p1` | Complete unknown-peer RAW receive path with original frame/FCS bytes and skb ownership preserved |

The first four patches exactly reproduce the retained v6 source on their
affected files. Patch 5 adds the final v8 native and peer-rate changes. Patch 6
adds the validated compact RAW handler from v9. All nine source differences
between the retained v6 and v9 trees are accounted for by patches 5 and 6.

`source-series-v9.json` pins the baseline and final hash of every file, all six
patch hashes, the precise target and the original baseline manifest. A null
baseline hash means that the rate header must be absent before replay.
`verify-source-series.py` verifies these identities, dry-runs every patch with
zero fuzz, then applies the complete series to a private temporary fixture and
checks the final hashes. It edits no original source, accesses no phone and
performs no kernel or ROM build.

```sh
python3 verify-source-series.py --baseline /path/to/exact/accepted/modules
```

The retained export receipts `replay-receipt.json` and
`verifier-checks-receipt.json` record the successful six-patch/11-file replay and
rejection of a changed baseline, an already-present new file, and a changed
patch. They are stored alongside the retained export fixture in
`continuation-apfree-20261118/durable-driver-export/`; they are not KSU payload
files. That exact `baseline/` fixture was reconstructed from the first
successful private DDK source copy by reversing its original two-file lifecycle
patch. Every restored file was checked against the accepted artifact's source
manifest before replay.

The unchanged installed kernel, its generated headers/configuration, original
DDK objects and dependency modules remain the build inputs. Use the retained
DDK incremental recipe when rebuilding QCA. A fresh generic kernel build can
change those inputs and does not establish compatibility with this payload.

The earlier Mosey Extended Magisk/KernelSU module and OPAirDrop module/config
adapter were consulted again; their inspected file hashes are recorded in the
manifest. This series is specific to the accepted Onyx QCA target. Native
discovery, radio reception, file transfer, cleanup and boot persistence require
their own device receipts; a successful source replay establishes the source
identity only.
