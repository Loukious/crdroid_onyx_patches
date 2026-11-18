# Onyx Mosey flag and boot helper

Provider **2026.11.18.10** releases the module's former country/channel pin while
retaining the native adapter and both enabling Booleans. The live update verified
that the CE and shared-cache country overrides were absent, the hopping Boolean
remained true, the provider foreground delegate was ready, and the cache's
compressed suffix was unchanged. A separate phone trial selected **channel 149
at 5745 MHz** with no host Wi-Fi peer running, then restored Asus Wi-Fi after
Quick Share closed. This verifies phone channel selection; 5 GHz reception and
file transfer over the air remain unverified.

- Package: [onyx-mosey-gms-20261118-v10.zip](out/onyx-mosey-gms-20261118-v10.zip)
- SHA-256: `40486aafb671b477d67464ae0538c6a7c8f73d3acf5880fdb3598cf8157912bb`
- Channel policy and receipts: [PHONE-CHANNEL-POLICY.md](PHONE-CHANNEL-POLICY.md)

Persistent v10 boot activation and first-unlock verification passed with SELinux
Enforcing. The reboot retained country-override absence in CE/shared cache,
the hopping Boolean and a ready provider foreground delegate. See the
[post-unlock receipt](/home/loukious/Android/onyx-wonder-coex-dev-20261117/mosey-activation-fix-20261117T161143423932Z/goal-working-20261117/native-capability-integration/continuation-apfree-20261118/phone-channel-unpin-v10-post-unlock-20261118T182525.102349Z/receipt-private.json).
The retained provider v9/driver v10 trials already verified persistent boot
activation, registration, a 40,603-byte phone-to-WSL file, and normal Wi-Fi
restoration on channel 6. Later provider v9/driver v15 trials verified native
multicast mDNS and a 208,896-byte stock Owly transfer to the phone. Those file
results precede this country-unpin update; the historical receipts remain valid
for their tested packages and channel. See [driver validation](../onyx-wonder-driver-ksu/README.md).

This KernelSU/Magisk module now persists two inspected Phenotype overrides:

- `com.google.android.gms.nearby` / `45704091`: boolean true for the external provider.
- `mosey_app_android#com.google.android.mosey` / `45768305`: boolean true to enable the APK's real native channel-hopping capability query.

Country map `45718707` is unmanaged after a one-time release of our legacy
change. An upgrade restores the exact prior country value or removes an exactly
owned module-created entry using its independent baseline. Fresh installs create
no country entry. Other country policy, including the captured PS/channel 44
value, is preserved; later genuine server updates remain unmanaged.

It starts the bundled `ExternalSharingService` after first unlock, with the
foreground-service delegate required by the examined Android 17 boot session.
The helper publishes the hopping Boolean into the existing GMS shared primary
cache and separately releases any legacy country metadata. Historical versions
6 through 9 published both app flags there. Updating the database or refreshing
the app's fallback alone leaves the APK's actual getters on old primary values.
The shipped GMS debug override
API rejects this build with `com.google.android.gms is not authorized for debug operations`.
The hopping flag enables the query and native software channel retuning. The
Onyx adapter validates fresh driver capabilities but reports controller
hopping=false: shared traffic is supported only on the exact STA home channel.
With DBS unsupported, the app uses its normal STA disconnect and restore policy
before AP-free startup. Android DBS and Wonder HBS remain separate capabilities.

It requires Onyx, Android SDK 37, GMS version code **264630035** (26.46.30),
Mosey APK version code **60715**, Phenotype schema **1036**, and a native Android
`sqlite3` command already on PATH. Other GMS/APK versions are rejected until their
flag contracts have been inspected.
The version check reads the active installed package section and excludes the
older prebuilt listed under `Hidden system packages`.
The unlock gate uses Android 17's verified `cmd activity get-started-user-state 0`
response `RUNNING_UNLOCKED`. Framework executables are pinned to `/system/bin`
for KernelSU's standalone shell.
It does not install or downgrade GMS/Mosey, clear app data, change unrelated flags,
or disable SELinux enforcement. The package includes the runtime-validated native adapter at
`system/system_ext/lib64/libmosey_onyx_config.so`; it uses the already installed
ROM launcher and service. No ROM image is required for this update.

Build and validate from this checkout:
Host validation requires `sqlite3` and a real `mksh` executable. If `mksh` is
outside PATH, set `MOSEY_TEST_MKSH` to its absolute executable path.

```bash
python3 tools/onyx-mosey-gms-ksu/test_module.py
python3 tools/onyx-mosey-gms-ksu/native/test_wonder_capability_bridge.py
python3 tools/onyx-mosey-gms-ksu/native/test_wlan_regulatory.py
python3 tools/onyx-mosey-gms-ksu/native/build-cache.py --ndk /path/to/android-ndk \
  --output tools/onyx-mosey-gms-ksu/native/onyx-mosey-cache-v10-arm64 \
  --receipt tools/onyx-mosey-gms-ksu/native/build-cache-v10-receipt.json
python3 tools/onyx-mosey-gms-ksu/build-module.py \
  --policy-helper tools/onyx-mosey-gms-ksu/policy-helper/onyx-mosey-nlmsg-arm64 \
  --policy-clearance tools/onyx-mosey-gms-ksu/policy-helper/build-receipt.json \
  --cache-helper tools/onyx-mosey-gms-ksu/native/onyx-mosey-cache-v10-arm64 \
  --cache-clearance tools/onyx-mosey-gms-ksu/native/build-cache-v10-receipt.json \
  --native-library /path/to/validated/libmosey_onyx_config.so \
  --native-clearance /path/to/native-v9-live-clearance.json \
  --output /tmp/onyx-mosey-gms.zip
```

Historical version 7 added the native adapter that reads and passes the actual `wlan0` vendor
regulatory country to Wonder while preserving the app's requested channel list.
The native source/build review, capability transaction 4 and a 60-second enforcing
discovery trial match artifact SHA256
`cbea39cae18ca05e851e6005895de55e4956bcf1e5eeb8f06bd0dd43bc43f40f`.
The QCA driver required the separately packaged `onyx_wonder_driver` revision 3
receive-header fix for that trial. At that stage, actual TCP/file transfer and
boot persistence remained under validation; discovery alone did not establish them.
The version-7 package was held pending the final measured neighbour-policy helper
and a clean discovery stop/restart check. Existing version-6 ZIPs retain their
original native library and policy helper; their clearance cannot be used for v7.
To rebuild a package containing the adapter, also pass `--native-library` and
`--native-clearance`; the builder rejects an artifact without its matching
Mosey-domain, Enforcing validation receipt.

Install the ZIP through KernelSU/Magisk after its exact native and helper receipts
pass. The historical v7 trial used a reversible native-library bind and the
running v3 QCA payload; both installed modules were disabled for automatic startup.
The current module directory can still contain an older payload while a newer
payload is running or queued in `modules_update`; inspect hashes and disable
markers in both locations before enabling persistence. Installation can clear the
current module's disable marker, so a guarded update must restore it until boot
validation is ready. Revision 4 was installed and
verified across a real KernelSU Next reboot on Onyx on 2026-11-17; see
[device validation](DEVICE-VALIDATION-20261117.md). The native Mosey/Wonder ROM integration must
already be installed. Its source is reproduced by
`scripts/vendor_lineage/0010-onyx-mosey-source.sh` and `assets/onyx-mosey-source`.

Historical version 9 changed only the native bridge's controller hopping result within the
existing Onyx Wonder profile. It retains fresh GET_CAP validation, the stable
Parcelable, native config field 5=true, WLAN country handling and normal cleanup.
The launcher and package build contract are unchanged. Portable actual-source
tests cover activation boundaries, fresh queries, Binder errors and forwarding;
module packaging still requires the exact native artifact's live validation
receipt. Channel hopping across the normal AWDL social channels and actual
iPhone interoperability remain unverified.

## Database changes

DE is inspected early only when its existing Nearby registration is available
and the running package manager can confirm the exact GMS version. CE is opened
after user 0 unlocks. A missing DE registration is skipped. A missing CE
registration is retried briefly, then rejected without creating a registration.

Before changing either database, SQLite makes a coherent root-only backup under
`/data/adb/onyx-mosey-gms`. Nearby keeps `{de,ce}-before.sqlite`; the additional
Mosey Boolean changes in v10 use independent
`{de,ce}-mosey-bool-v10-before.sqlite` files. Legacy
`{de,ce}-mosey-before.sqlite` files remain untouched as country-release evidence.
The new Boolean baseline is captured after country release. GMS and APK version
markers guard these backups, and metadata-write failure prevents the Boolean
transaction.
The two schema-1036 layouts have distinct SQL: DE has the four-column override
table `(config_package_id,name,value,type)`; CE has the account/state/link tables.
Each write uses one `BEGIN IMMEDIATE` transaction. CE changes only the active
account-zero overrides and links them to the committed and latest existing
experiment states for their namespace/account. DE changes only the named flags
when that namespace already exists. Existing IDs, source metadata, other accounts
and flags are retained. WAL/SHM files are never copied or deleted.

Both managed Boolean values use SQLite integer/type 2. Country-release SQL
targets only legacy `45718707` ownership and validates its original value,
type, source and CE links before restoring or removing it. A baseline-bound
marker makes release idempotent and leaves later country updates alone.
An unknown writer or incompatible baseline rejects migration. The retained map
families and snapshots are migration evidence, not values inserted by new
installs. Their hashes are recorded in [flags-contract.json](flags-contract.json).

The startup service stops the Mosey APK and GMS publisher before shared-cache
migration or correction, then starts and verifies the provider delegate.
It does this even when the Boolean is already correct, because the country
release is independent. This can briefly interrupt sharing/GMS activity.

## Shared primary cache

The standalone ARM64 helper resolves the primary file from the APK's existing
CE storage-info file, including its dynamic secret directory and the exact
namespace filename. It accepts only the inspected shared storage configuration,
framing and compressed flagsets. Normal apply changes only the hopping Boolean
in protobuf metadata field 5, including its internal field-10 flag name.
The separate `--release-country` action restores or removes only the legacy
country entry under its original ownership proof. The
compressed payload, tokens, other metadata and unrelated overrides remain byte
identical. Publication uses a guarded atomic replacement preserving the original
file owner, mode and SELinux label.

An independent root-only baseline is kept under `/data/adb/onyx-mosey-gms`, keyed
by the resolved primary path. Existing database backups stay untouched. Repeated
application leaves an already correct cache unchanged. The v10 Boolean baseline
uses `cache-overlay-bool-v10-<path-digest>-*`; the original
`cache-overlay-<path-digest>-*` files remain country-release evidence. The
service stops the APK and GMS publisher before invoking country release or
cache correction, even when database values are already correct.

Rollback restores only the v10-owned Boolean metadata value while retaining
newer unrelated fields and payload/tokens. Entries created from absence are
removed only if they still match the helper's own complete entry. Unsupported
values, changed ownership or concurrent file changes reject publication.

Disabling/removing the module stops future boot actions; persisted GMS overrides
remain. To undo a change made by this module, while unlocked and rooted, run:

```bash
sh /data/adb/modules/onyx_mosey_gms/rollback.sh
```

Rollback restores only each managed Boolean's previous value/source, or deletes
its active row and references if its independent baseline had no row. It does
not restore an entire stale GMS database or reintroduce the old country pin.
It checks the active GMS and Mosey APK versions before disabling the module or
changing state, then stops the provider delegate/service and both cache consumers
before restoration. Backups remain available for inspection.
Disable the module and reboot to remove a live native policy grant that was
absent from the ROM's original boot policy and remove the module's library
overlay. Rollback does not replace the running policy with a stale snapshot.

## Native policy and diagnostic evidence

The native daemon needs `RTM_SETLINK` (19 / `0x0013`) to bring `wonder0` up,
`RTM_GETLINK` (18 / `0x0012`) to query it, `RTM_GETNEIGH` (30 / `0x001e`) to
query neighbours, `RTM_NEWNEIGH` (28 / `0x001c`) to create a neighbour entry,
and `RTM_DELNEIGH` (29 / `0x001d`) to remove it at peer expiry. Each addition
followed an enforcing denial during the corrected driver trial.
The source asset and default helper include these five precise grants.
The tested `ksud` live parser encoded `nlmsg` as an ioctl xperm,
so this ZIP carries no `sepolicy.rule` or captured full-policy image.

The small ARM64 `policy-helper` instead reads the current live policy using
AOSP libsepol and adds only the Mosey base `nlmsg` permission plus NLMSG 18/19/28/29/30.
It corrects the exact erroneous one-bit ioctl rule if that rule is present.
It preserves policy version, capabilities and permissive domains, validates
its output, and rereads the current policy before its single policy-load write
to reject concurrent changes. SELinux must stay Enforcing. Repeated application
does not reload an already correct policy. Boot startup is skipped if it fails.
Offline tests compare every decoded policy record and verify byte-identical
reapplication. The live GETNEIGH update added only 30 alongside the existing
18/19 grants; the complete decoded live policy matched the reviewed proposal,
SELinux remained Enforcing and reapplication left the dumped policy byte-identical.
The loaded 18/19/28/30 policy was captured for the subsequent DELNEIGH upgrade.
The latest helper passed six real policy inputs and eight preservation cases;
independent fresh decoding verified all fourteen cases. The current-policy
upgrade adds only 29, and every repeated output is byte-identical. Its pinned
binary, receipts and prior builds are in
`policy-helper/verification/delneigh-20261117T233211Z/`. The default helper and
build receipt now match that verified candidate. These are host checks; live
application is validated separately. Existing version-6 ZIPs contain the older
SETLINK-only helper; packaging v7 uses the newly verified default files.

On 2026-11-17, a complete GMS service dump omitted its unconditional
`Registered providers:` heading, proving effective flag `45704091=false`.
A guarded transaction enabled it; GMS carried the override into a later committed
state. The official `FLAG_OVERRIDE` broadcast was delivered but a true/false
roundtrip did not change this row, so it is not used here. Native Binder/package
presence and a verified CE override gate the boot provider startup. Binder is
polled briefly at boot. Once present, only the provider component is re-enabled
if the APK boot receiver disabled it; a user-disabled package is respected.
Startup then verifies a live provider ProcessRecord and a foreground delegate
in their respective service records, with matching PIDs and bounded retries.

## References and validation status

- [mosey-extended](https://github.com/thelok1s/mosey-extended) supplied the original
  root-module reference. Its guessed flag names, APK downgrade/data clear, virtual
  RF driver, and WAL removal are not used by this implementation.
- [OPAirDrop](https://github.com/Weverses/OPAirDrop), especially
  [provider.sh](https://github.com/Weverses/OPAirDrop/blob/main/module/bin/provider.sh),
  informed component restoration, provider/delegate validation and pinning
  Android framework commands under KernelSU.
- [Google Wonder](https://android.googlesource.com/kernel/common-modules/wonder/)
  supplies the upstream kernel transport; the Onyx ROM uses its source-built
  Wonder/QCACLD integration separately from this module.

Revision 4 passes 17 host tests, including separate CE/DE transactions, scoped
rollback, hidden-system APK version parsing, the verified Android 17 unlock API,
and record-local provider/delegate checks. Revision 3's device run exposed an
Android mksh difference: unescaped `|` is alternation in parameter expansions,
so the matching `30078|30078` PID pair was split incorrectly. Revision 4 uses
a colon delimiter. A startup regression runs under real mksh and verifies ready
status for matching records, bounded failures for absent/mismatched records, and
one delegate request when necessary. It fails against revision 3's code.
The parser also matches the captured phone service dump. The packaged revision 4
was installed and its automatic startup verified after a real reboot and first
unlock. The ARM64 policy helper applied its precise NLMSG grant during boot;
decoding the loaded policy confirmed NLMSG 19 and no erroneous ioctl 19 grant.
SELinux remained Enforcing. GMS registered the Mosey provider and the module
verified its live service and foreground delegate.

## Historical revision 4 runtime limitations

At that stage, native driver initialization returned EBUSY. Mosey explicitly disconnected
Wi-Fi before startup when DBS is unsupported, leaving the STA interface up.
Tracing confirmed the same CM context transitions from connected to disconnected
before the native requests. That state satisfies neither the connected-owner
coexistence path nor the current standalone path, which requires STA down.
DP and firmware capability checks passed. A supported native handoff or a
preserved same-channel STA is still needed; successful AirDrop discovery or
transfer has not been established.

A one-shot standalone handoff trial ended in its userspace restoration
watchdog's normal reboot. Recovered previous-boot kernel logs show successful
deletion of both STA vdevs within about 29 ms, followed by native startup
errors during a firmware idle shutdown/restart sequence. They do not establish
a STA-stop deadlock: native startup/cleanup or the following interface query
may have stalled. No persistent interface-down workaround was added, and the
phone's original saved Wi-Fi connection and setting baselines were restored.

## Historical version 5 native capability validation

The native adapter now bridges transaction 4 for the exact Mosey Binder
interface. It reads the real Wonder GET_CAP result through a bounded nl80211
wiphy dump and vendor query; no sysfs permission is added. A Java client
verified the original service version/hash and decoded hopping=true from the
stable Parcelable while the service remained in `mosey_server` and SELinux
Enforcing. HBS remained false. Canonical REA APK evidence verifies the
transaction and disconnect gate. The adapter does not change DBS/HBS.

The historical version 5 country-pin implementation passed 28 host module tests.
Both absent-country snapshot guards were tested,
as are explicit map preservation, private independent upgrade baselines, typed
CE/DE transactions, rollback, version gates and actual mksh startup behavior.
The final package reproduces byte-for-byte. On-device application changed only
the two scoped CE app overrides, skipped unregistered DE, preserved the original
version-4 Nearby baseline, and restarted the live provider with a matching
foreground delegate. Actual radio discovery and transfer validation are pending.

## Current v10 source validation

The v10 source passed 40 module tests under real mksh, 49 shared-cache tests,
and an actual-script rollback APK-version guard test. Coverage includes fresh
Boolean-only installs, country-only upgrades, preservation of PS and other
country entries, server updates after release, versioned backups, scoped
rollback, metadata-write failure and stopping cache consumers before publication.
The ARM64 cache build and its exact sources are bound by
`native/build-cache-v10-receipt.json`; live and persistent validation are separate.
