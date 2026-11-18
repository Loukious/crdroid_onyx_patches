# Bluetooth/hotspot follow-up (kernel investigation)

No new ROM patch is justified by the current captures. Existing camera/ROM SELinux findings and the prior miev policy patch remain separate.

The installed ROM already gives /dev/bt_cp_ctrl bluetooth:system 0660 in device/xiaomi/onyx/rootdir/etc/ueventd.qcom.rc. The device node is missing because its native glink_pkt kernel provider has not been ported. Firmware advertises bt_cp_ctrl and the vendor Bluetooth library requires that control device before opening the codec DMA transport. Restore and validate the kernel provider before assessing any further ROM fix.

Both vendor HAL variants default persist.vendor.qcom.bluetooth.is_cp_supported to true. An absent property does not establish a mismatched default. Do not override it or replace native transport behavior based on the current evidence.

Hotspot reboots with and without tether hardware offload. No captured panic proves a ROM-side cause or a kernel crash site yet.

Detailed evidence: /home/loukious/Android/konoha-android17-6.18-platform-providers/validation/hotspot_bt_20261103/findings.md

Reboot follow-up: latest host check sees the already captured boot ID; generic reboot properties and empty pstore add no precise crash attribution. Kernel provider work continues in an isolated draft. No additional ROM change is warranted by this capture.

## Kernel candidate installed, 13:05 UTC

Native `glink_pkt` is installed in the matching 371-module artifact `20261103T125226341911Z`. `/dev/bt_cp_ctrl` exists with bluetooth:system 0660 and the existing `hci_attach_dev` label; the firmware channel binds to `glink_pkt_bt_cp_ctrl`. SELinux remains enforcing. No ROM permission or property change was needed for this channel. User Bluetooth playback testing is pending. No confirmed hotspot fix is claimed.

Installation: /home/loukious/Android/konoha-android17-6.18-port-20261031/device-backups/5493f3c6-20261101T160034Z/logging-investigation/bluetooth-glink-371-20261103T130225Z


Bluetooth user retest passed with native DMA acknowledgements returning 0 and SBC 44100 Hz PLAYING sessions. Hotspot v10 establishes a kernel NULL wiphy mutex dereference in HDD channel-change notification locking. A kernel compatibility fix is building; no ROM fix is required by this evidence. Existing camera/SELinux ROM findings remain separately recorded.

Kernel patch 0212 is now installed in artifact 20261103T135741329740Z. Both connected-Wi-Fi and Wi-Fi-off AP startups remain active for 45 seconds without a reboot. Saved hotspot configuration hash unchanged; Wi-Fi restored and connected. User Settings/tethering test pending. No ROM change was needed for these AP startups.

User confirms the Settings hotspot toggle now stays on. Kernel-only WLAN locking fix resolves the captured reboot; no ROM edit was required. Connected-client internet forwarding remains untested.

## Hotspot band policy verified

The later band-selection investigation establishes a separate ROM configuration
issue. Vendor `gWlanMccToSccSwitchMode = 3` forces Wi-Fi and hotspot onto the
same channel, so a 2.4 GHz hotspot request becomes 5260 MHz alongside the station.
The normal STA+SAP driver combination allows two interfaces and two channels.
Missing dual-band simultaneous support does not rule out channel time sharing.

Changing only the effective INI policy to mode 0 and fully reloading the original
installed WLAN module starts STA5260+AP2462. Effective configuration and the
native mode getter both report 0. The current firmware does not advertise
`NO_INTERBAND_MCC_SUPPORT`; no firmware or kernel code modification was needed.
The user confirms the attached client's internet works with native Android
tethering active. The first diagnostic AP-only start omitted the tethering
request and therefore did not establish a DNS fault.

Patch `device_xiaomi_onyx/0017-allow-sta-hotspot-different-channels.patch`
sets the source INI policy to 0. `device.mk` already copies it to the effective
vendor path. `apply.sh` picks up the patch automatically, and `gen-patches.sh`
regenerates only its policy hunk, excluding the independent CFR setting.
Rebuilding and installing the ROM is required for permanent deployment.
The phone currently uses a temporary mode 0 overlay left active at the user's
request; the ROM patch itself has not been built or flashed.

Controlled runtime evidence:
`/home/loukious/Android/konoha-android17-6.18-platform-providers/validation/hotspot_bt_20261103/hotspot-mcc-runtime-validation.json`.

Validation passed on an isolated checkout of the current device tree: forward
and reverse application, the real apply.sh patch function applied once then
skipped on rerun, and the real generator reproduced the patch while excluding
the existing CFR change. Shell syntax and changed-file whitespace checks pass.
The local ROM source and phone partitions were not modified by patch validation.
