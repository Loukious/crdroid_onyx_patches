# Native Onyx Mosey source overlay

Current device validation (2026-11-18): provider **2026.11.18.10** with driver
**2026.11.18.15** passed persistent boot activation and first-unlock provider
validation with SELinux Enforcing. Provider v10 releases only the module's old
country/channel pin; CE and shared-cache country overrides remain absent after
reboot, the hopping Boolean is preserved, and the foreground delegate is ready.
A separate trial selected phone channel 149 at 5745 MHz without a host Wi-Fi
peer, then restored Asus Wi-Fi on close. This verifies channel selection, not
5 GHz reception or file transfer over the air.

Earlier provider v9/driver v15 channel-6 trials verified native multicast mDNS
and a 208,896-byte stock Owly transfer to the phone with the exact source hash.
The earlier provider v9/driver v10 trial delivered 40,603 bytes to WSL and
verified ordinary Wi-Fi restoration. These historical file receipts precede
the country-unpin update. See [phone channel policy](../../tools/onyx-mosey-gms-ksu/PHONE-CHANNEL-POLICY.md)
and [driver validation](../../tools/onyx-wonder-driver-ksu/README.md).

5 GHz transfers, full channel hopping, simultaneous STA/AWDL service, MLO,
large files, long-duration stability and iPhone interoperability remain
unverified. The phone update uses the KSU package; no ROM rebuild is required.

`scripts/vendor_lineage/0010-onyx-mosey-source.sh` validates `manifest.json`,
copies `files/` into `vendor/extra/mosey`, and adds only the Mosey product and
private-policy includes. It runs for the Onyx 6.18 source recipe and preserves
other vendor-extra configuration. No GMS or native Google blob is modified.

The launcher/config adapter select the existing Wonder backend. The private
policy additionally grants NLMSG `RTM_GETLINK` (`0x0012`), `RTM_SETLINK`
(`0x0013`), `RTM_NEWNEIGH` (`0x001c`), `RTM_DELNEIGH` (`0x001d`), and
`RTM_GETNEIGH` (`0x001e`) to the native
Mosey daemon, alongside its existing bind/setopt and launcher exec permissions.
The SETLINK source grant passed generated-policy checks on 2026-11-17. The later
GETLINK addition was identified by a live denial and verified through complete
binary-policy preservation tests and an enforcing live KSU helper trial.
GETNEIGH was subsequently denied during the v7 adapter/v3 Wonder RX-header
trial. Its helper upgrade from the current 18/19 policy is checked offline for
the exact single-record addition and byte-idempotence, including complete
grants split across records and unrelated-record preservation. After GETNEIGH
was loaded successfully, NEWNEIGH 28 was denied in the same enforcing Mosey
domain. The NEWNEIGH-only upgrade from the captured 18/19/30 policy passed
offline and live checks. Peer expiry then exposed a DELNEIGH 29 denial. The
latest helper upgrade from the captured 18/19/28/30 policy must add only 29;
the complete grant is 18/19/28/29/30. These source changes do not require a ROM
build for the current KSU update.

The GMS flag and provider boot helper are separately maintained in
`tools/onyx-mosey-gms-ksu`. The root module can install the validated configuration
library on the already flashed ROM, which contains the launcher and service.
The source overlay preserves the same adapter for future source builds; the
current phone update uses KSU and does not require rebuilding a ROM image.

The configuration library supplies the installed APK's capability transaction
after a fresh read-only Wonder GET_CAP command. Under the existing Onyx Wonder
profile it reports controller hopping=false, so the app can use its normal Wi-Fi
disconnect and restore policy. Native config field 5 remains true for software
channel retuning. The driver supports idle unassociated startup and shared
traffic on the exact STA home channel. HBS/DBS and foreign-channel guards remain
independent. The adapter resolves the wiphy through nl80211, preserves the stable
Parcelable and existing Binder calls, and exports only `dlsym` and
`AIBinder_Class_define`.
