# Onyx reviewed Wonder QCA driver companion

Driver package **2026.11.18.15** transmits native group-addressed AWDL data on
the established exclusive Wi-Fi channel. The installed build passed ordinary
and QoS multicast probes on channel 6. Stock Owly then discovered the phone and
delivered **208,896 bytes** with the exact source SHA-256; Quick Share restored
Asus Wi-Fi after close. The host radio captured six phone mDNS frames carrying
the AirDrop service with the original multicast destination
`33:33:00:00:00:fb`.

- Package: [onyx-wonder-driver-20261118-v15.zip](out/onyx-wonder-driver-20261118-v15.zip)
- Package SHA-256: `77a918d755b4248fb06d6c25130cbf424338b3df7d0451cfe88ca51ff8b7e7d8`
- QCA payload SHA-256: `3b2e60fd74a61cb931f2d79c16658b3d551cf2f5bc82df5fe642c0cfd2f8dc51`
- Running GNU build-note SHA-256: `29fb8c4b6118219ad19d2436706c31a14b57e87937afed9ec099b7b8fca5cdc8`
- Source replay: [source-series-v15.json](source-series-v15.json) and
  [0008-wonder-native-awdl-multicast.patch](source-patches/0008-wonder-native-awdl-multicast.patch)

The default-enabled, read-only `wonder_native_group_tx` parameter selects the
existing WMI raw transmit command `0x7009` for eligible plaintext, unfragmented
AWDL group data. A zero command frequency uses the already established helper
channel. Helper identity, exclusive channel ownership, regulatory checks and
DMA completion ownership remain enforced. The firmware assigns the outer
802.11 sequence number and uses intrinsic group no-ACK behavior; the original
radio addresses, AWDL sequence and packet contents are preserved. This route
does not preserve an externally selected outer Wi-Fi sequence number.

The command consumes a 16-bit descriptor ID. IDs are reserved synchronously
before accepting the packet and never recycled during the module lifetime,
including after a queued send is canceled. After **65,535 reservations**, or
when native admission otherwise fails, mDNS can use the retained v12 delivery
to individual AWDL peers. Other group traffic may be rejected after exhaustion.
ASan/UBSan tests extracted from the production functions verify reservation,
parallel admission, rejection ownership and the mDNS fallback; dependency
behavior is mocked, and hardware exhaustion has not been exercised.

The native probe receipt records 14 ordinary and 12 QoS frames received at
`33:33:00:00:00:01`, with matching unicast controls. WMI reported 60 sends and
60 completions, zero failures and no pending mappings. The later stock transfer
verified SHA-256
`88a3b76fb7cba053c2b89da960a7f75ac06e40f2271840ef6e1b2304910d9d87`
against independently read phone bytes. Its earlier failed transfer receipt is
retained separately; it proved native mDNS reception but did not verify file
delivery.

See the [native probe receipt](/home/loukious/Android/onyx-wonder-coex-dev-20261117/mosey-activation-fix-20261117T161143423932Z/goal-working-20261117/native-capability-integration/continuation-apfree-20261118/native-multicast-tx-20261118T174305.410657Z/receipt-private.json)
and [stock discovery and transfer receipt](/home/loukious/Android/onyx-wonder-coex-dev-20261117/mosey-activation-fix-20261117T161143423932Z/goal-working-20261117/native-capability-integration/continuation-apfree-20261118/native-multicast-discovery-20261118T174739.152518Z/receipt-private.json).
This result covers the channel 6 WSL peer. Simultaneous STA/AWDL operation,
5 GHz, full channel hopping, MLO, large files, long-duration stability and iPhone
interoperability remain unverified.

## Earlier driver v12

Driver package **2026.11.18.12** adds IPv6 mDNS delivery to recently heard AWDL
peers. The Qualcomm raw TX helper failed to transmit group-addressed data in
the channel 6 test. The driver sends copies of the discovery packets to nearby
AWDL peers using their individual radio addresses and preserves the multicast
IP packet and A-MSDU contents. Stock Owly discovered the phone by name and
completed a WSL-to-phone file transfer on channel 6.

- Package: `out/onyx-wonder-driver-20261118-v12.zip`
- SHA-256: `4fe5f82d520de8e3ef3d67c1552fc3afd88cb069a74e1adf8969693184034e0d`
- Source replay: `source-series-v12.json` and
  `source-patches/0007-wonder-awdl-mdns-peer-tx.patch`

Driver package **2026.11.18.10** introduced the reviewed compact RAW receive,
unassociated STA startup, destination-compatible transmit-rate and boot-lock
fixes. Its QCA payload passed the installed ABI checks and loaded successfully
in a controlled live trial. This companion packages only QCA; the ROM, boot
image, kernel configuration and dependency modules remain unchanged.

Use it with Mosey provider package **2026.11.18.9**, which supplies the matching
native capability/country/shutdown adapter and ordinary STA handoff. Starting
from Asus Wi-Fi at 5240 MHz, Quick Share automatically disconnected the STA and
delivered **40,603 bytes** to WSL with the exact source SHA-256 on channel 6,
without a manual disconnect, AP join or rate override. A separate Back-button
discovery-close trial restored Asus/autojoin and removed the AWDL interfaces.

Driver v10 and native v9 persistent boot activation subsequently passed with
SELinux enforcing. First-unlock provider registration and flag/cache checks
also passed. The earlier native v8 boot/first-unlock checks and
controlled **19,565-byte** AP-free transfer remain retained validation.
See [device validation](DEVICE-VALIDATION-20261118.md).
See [the source reproduction instructions](SOURCE-SERIES.md).

The stock QCA module is loaded by the vendor loader at `early-init`. A normal KSU
overlay is therefore too late for its initial load. This module uses `skip_mount`
and a synchronous `post-fs-data.sh` hook to unload only QCA and insert its private
payload before zygote and Android Wi-Fi start. It skips replacement if any guard
fails. It has no later service hook. The separate `live-test.sh` source helper is
never included in the ZIP and requires an explicit root invocation after root
stops the Mosey provider/native, disables Wi-Fi and stops Wi-Fi HAL/supplicant.
It reuses every identity/radio/refcount guard while omitting early-boot/zygote
checks. It never stops zygote or starts/stops any Android service.

## Frozen target and runtime guards

- Onyx, Android SDK 37, kernel `6.18.63-android17-6-maybe-dirty-4k`.
- Vendor QCA SHA256
  `0a2eba04b57ccdc0ae9e57258b91b38440e4b983fa9e151fe5acf36a3d915969`.
- Exactly the reviewed vendor options: `sta_monitor_coexist=1`,
  `ap_monitor_coexist=1`, `sta_ap_monitor_coexist=1`, `wonder_enabled=1`.
  Their current safe bool sysfs values must also be true. Other module parameter
  callbacks and statistics are never passed back to `insmod`.
- `vendor.all.modules.ready=1`, vendor modprobe stopped, zygote stopped/unstarted
  with no zygote process, boot not
  complete, native Mosey/Wi-Fi HAL/supplicant/hostapd stopped, no Mosey APK/native
  processes, and all wireless interfaces down. Visible coexistence stats must
  report `active=0`.
- QCA live, sysfs and `/proc/modules` refcount zero, no holders. If available,
  the running QCA GNU build note must match the stock build note.

Reload exclusion uses `/data/adb/onyx-wonder-driver/reload-<boot-id>.lock`.
An interrupted attempt remains excluded within its own boot; its stale lock
cannot block a later boot. The selected boot identity is rechecked around the
final preflight. A private per-boot attempt ledger also prevents a second reload.

The four init parameters, original options file and independently verified stock
module are saved under `/data/adb/onyx-wonder-driver/<boot-id>/` before a final
preflight. Both insertion files receive the stock `vendor_file` SELinux label
before unloading. A successful replacement must expose the getter-only
`wonder_lifecycle_revision=1` and its exact reviewed running GNU build note.
A normal `rmmod` rejection leaves the stock driver loaded. A rejected
replacement insertion triggers stock `insmod` with the same four init arguments
only when no QCA module remains. Rejection disables the future boot hook to avoid
repeating the attempt. Disable and reboot restores the original vendor load.

No forced unload is used. A userspace timeout cannot unwind a blocked kernel
unload or insertion: the source lifecycle/unload review is required before this
scaffold can be packaged. These guards are conservative observations, not a
kernel-wide lock against another actor opening an interface. Early synchronous
execution reduces that race; it does not prove runtime hardware compatibility.
Without a readable running build note, identity relies on the frozen vendor
module, completed vendor loader, exact kernel release and accepted ABI baseline.

## V10 package and source

`out/onyx-wonder-driver-20261118-v10.zip` has SHA256
`2a5b961cab8e7ee801a2b7e3eaf42bd292fed1f59c5e37588b7dd89e4bc566ad`.
The matching provider ZIP is
`tools/onyx-mosey-gms-ksu/out/onyx-mosey-gms-20261118-v9.zip`, SHA256
`1be84662d42aed6082048f56cb7869706fb59727182da66f3a706ce524c3649b`.
Its visible native shim SHA256 is
`f954dac6eb4bb2768dada78b6e0b79894e24cca1b343e5ffe3d3ef81914de322`.
The v9/v10 QCA payload is byte-identical: SHA256
`54cf09f0dc27ac41eb9ce1cdc4bd4b5046d374520b4d773330d3a1a580b0b1d7`,
running GNU build-note SHA256
`14fa9fb0293e94e01e74d2e43edcf541bad856e5b9f11631c27497d1aa070e35`.
All 566 imported symbol CRCs and 993 exports match the installed ABI.

The six patches in `source-patches/` reproduce all 11 reviewed modified or new
files; the source verifier applies them with zero fuzz to a temporary copy.
`test_module.py` covers the identity/unload/rollback behavior, and
`test_boot_lock.py` covers boot changes, concurrency and stale locks.

The first live v9 upgrade was interrupted after slow process guard sweeps
consumed its 60-second host timeout. A subsequent guarded load with sufficient
controller lifetime succeeded. Live helpers must remain connected until the
reload and its rollback/identity checks finish; killing the ADB controller at
an arbitrary deadline can interrupt insertion. Android background scanning
must be stopped through `cmd wifi set-scan-always-available disabled`, with its
original runtime setting restored afterward. Writing the global settings row
alone did not stop the active scan-only client manager on this target.

The current RTL8188CU USB test peer supports only 2.4 GHz and one spatial stream,
and its Owly backend uses channel 6. The controlled native v8 AP-free transfer
and matching foreign TCP acknowledgments validate phone reception of replies on
that channel. Native v9 then passed normal startup and a fresh full-file transfer
from an existing Asus connection without a manual handoff. Its Binder capability
reports `channel_hopping_supported=false` to use the application's STA-disconnect
path; the daemon still logs `StartMoseyConfig channel_hopping=true`. The ordinary
STA is disconnected during AWDL; simultaneous Asus connectivity is unverified.
The hidden host AP supplies USB channel/ACK context; the phone does not join it.

First-unlock provider registration and reverse file transfer passed with
provider v9. Tests for 5 GHz AWDL, social-channel hopping, MLO, large files,
long-duration stability and iPhone interoperability remain pending.

## Original retained DDK build

The original successful DDK cache is
`/home/loukious/Android/custom-rom/out/target/product/onyx/obj/KERNEL_BAZEL_OUT/kleaf-cache/1fdbe25f`.
Stripping its original QCA module reconstructed the installed baseline exactly:
SHA256 `0a2eba04b57ccdc0ae9e57258b91b38440e4b983fa9e151fe5acf36a3d915969`.
Its effective QCA configuration has SHA256
`043032ddb5ccd83e5de10f7e79f177fcfd9b4f4e936884374858dfa68a965407`,
ordinary unload enabled, forced unload disabled, modversions enabled and no
`CONFIG_WLAN_RESIDENT_DRIVER`.

The completed recipe copied that DDK into an isolated directory, preserved its
generated headers and existing objects, recompiled only `wlan_hdd_main.c` and
`wlan_hdd_wonder.c`, regenerated module metadata and relinked QCA. The original
cache remained unchanged. The resulting module SHA256 is
`a2bbf22608afc466b376a2c995069a1b114a8339698625b7d46a91781a0e8ec6`;
all **566 imported symbol CRCs** and **993 exported symbols** match the installed
ABI. The receipt status is `PASS_EXACT_INSTALLED_ABI_RUNTIME_PENDING`.

The recipe, metadata/link resume and successful receipt are retained here:

- [build-two-objects.py](/home/loukious/Android/onyx-wonder-coex-dev-20261117/mosey-activation-fix-20261117T161143423932Z/goal-working-20261117/native-capability-integration/wonder-driver-lifecycle-fix-20261117T201814462721Z/retained-ddk-build/build-two-objects.py)
- [resume-metadata-and-link.py](/home/loukious/Android/onyx-wonder-coex-dev-20261117/mosey-activation-fix-20261117T161143423932Z/goal-working-20261117/native-capability-integration/wonder-driver-lifecycle-fix-20261117T201814462721Z/retained-ddk-build/resume-metadata-and-link.py)
- [build-receipt.json](/home/loukious/Android/onyx-wonder-coex-dev-20261117/mosey-activation-fix-20261117T161143423932Z/goal-working-20261117/native-capability-integration/wonder-driver-lifecycle-fix-20261117T201814462721Z/retained-ddk-build/build-receipt.json)
- [baseline-reconstruction.json](/home/loukious/Android/onyx-wonder-coex-dev-20261117/mosey-activation-fix-20261117T161143423932Z/goal-working-20261117/native-capability-integration/wonder-driver-lifecycle-fix-20261117T201814462721Z/retained-ddk-build/baseline-reconstruction.json)

A generic Bazel build targeting only `//onyx:qca_cld3_wcn7750` still rebuilds
dependencies when their inputs differ. The attempted target changed the effective
kernel headers/configuration, Image and Symvers, then failed. Those outputs were
rejected. Use the retained DDK recipe for this replacement, preserving the frozen
kernel and dependency inputs.

## Package after review

After final independent clearance, copy `clearance.example.json` to a private
review receipt, replace the placeholder
digests, and record the completed independent review. The example intentionally
fails validation. The packager requires the compiled module and its QCA Symvers,
the accepted stock module, retained reference artifact, reviewed source root,
and successful review receipt binding the kernel sources and scaffold hashes.
It independently checks ELF architecture/module
name/vermagic, all 566 accepted imported names/CRCs, frozen exported QCA
names/CRCs/flags/namespaces and actual export sections, module parameter and
dependency contracts, reviewed source hashes, and frozen reference kernel hashes.
The clearance is a reviewer assertion bound to concrete artifacts, not a digital
signature or a device trial receipt. A new import or ABI change requires renewed
analysis; it cannot be waived with a boolean flag.

```sh
python3 tools/onyx-wonder-driver-ksu/test_module.py
python3 tools/onyx-wonder-driver-ksu/build-module.py \
  --module /path/to/reviewed/qca_cld3_wcn7750.ko \
  --replacement-symvers /path/to/reviewed/qca_cld3_wcn7750_Module.symvers \
  --stock-module /path/to/accepted-stock/qca_cld3_wcn7750.ko \
  --reference-artifact /home/loukious/Android/onyx-tracker-fix-20261116/workspace/artifacts/20261117T143428209411Z \
  --source-root /home/loukious/Android/onyx-wonder-20261116 \
  --clearance /path/to/review-clearance.json \
  --output /path/to/new/onyx-wonder-driver.zip
```

The output ZIP and adjacent JSON receipt must be new paths. Installation only
validates identity and permissions; it performs no reload. Root owns any device
trial and installation. Logs are in `/data/adb/onyx-wonder-driver/status.log` and
the private attempt directory. No SELinux policy changes or vendor overlays are
included.

The independent production-function lifecycle harness is
`tools/onyx-mosey-gms-ksu/native/test_wonder_lifecycle.py`. It checks the QCA lock
ownership and startup/unwind behavior separately from these host reload tests.
