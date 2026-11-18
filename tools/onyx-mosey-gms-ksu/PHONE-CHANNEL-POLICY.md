# Onyx phone channel policy, provider v10

Provider **2026.11.18.10** releases the module's former TN/channel-6 country
override. Its ZIP SHA-256 is
`40486aafb671b477d67464ae0538c6a7c8f73d3acf5880fdb3598cf8157912bb`.
The live update removed the owned country entry from the CE database and GMS
shared primary cache, preserved the hopping Boolean and compressed cache suffix,
and started a verified provider foreground delegate.

Without a host Wi-Fi peer running, Quick Share subsequently selected phone
channel **149 / 5745 MHz**. Closing Quick Share restored Asus Wi-Fi. This is
verified interface/firmware channel selection; it does not establish 5 GHz
reception, file delivery over the air or full channel hopping.

Persistent v10 boot activation and first-unlock verification passed with SELinux
Enforcing. After reboot, the country override remained absent in CE/shared cache,
the hopping Boolean remained true, and the provider foreground delegate was ready.

## Separate policy layers

| Layer | Current behavior |
| --- | --- |
| Country map `45718707` | Unmanaged after releasing only our old change. No country entry is created on a fresh install, and no replacement channel-149 override is written. |
| Hopping Boolean `45768305` | True, enabling the APK's real native capability query and its software channel-retuning configuration. |
| Native controller capability | The unchanged native v9 adapter reports controller hopping false for this Onyx profile, invoking Quick Share's ordinary STA disconnect/restore path. |
| WLAN regulatory country | The adapter passes the actual `wlan0` vendor country while preserving the application's requested channel list and driver regulatory validation. |
| WSL Owly peer | The tested RTL8188CU backend remains fixed on channel 6. Removing the phone's pin does not add 5 GHz support to that receiver. |

The observed channel 149 comes from the application's effective country policy
after the owned override is removed. The retained captured map has TN/channel
149 and PS/channel 44; the APK default map differs at PS. The update preserves
the genuine map family and every other country's policy instead of replacing
the entire map with APK defaults. Later genuine GMS country updates remain
unmanaged.

The hopping Boolean, daemon hopping configuration, controller capability,
regulatory country and radio peer's available channels are separate inputs.
Their values do not prove simultaneous STA/AWDL service, DBS/HBS, MLO or a full
AWDL social-channel hopping sequence.

## Country-only ownership release

Legacy providers changed only TN from channel 149 to channel 6 within a known
country-map family, or inserted a captured map when no override existed.
Provider v10 uses the original private CE/DE/cache baselines to release that
change. It restores the exact prior country value when one existed, or removes
an exactly owned module-created entry. It rejects changed value/type/source/link
ownership, incompatible snapshots and partial or corrupt baseline state.

Country release never restores a whole stale database or compressed flagset.
Other flags, accounts, country entries, protobuf metadata, tokens and compressed
payload remain intact. The original baselines are retained; release markers bind
to their identity and prevent later server or user country changes from being
reverted on subsequent boots.

New v10 Boolean backups use `{de,ce}-mosey-bool-v10-before.sqlite` and
`cache-overlay-bool-v10-<path-digest>-*`. They are independent of the legacy
country evidence. Rollback restores only owned enabling Booleans and leaves
country release and subsequent country updates intact. The script checks the
active GMS/Mosey versions before changing state. The startup service stops the
APK and GMS publisher before cache release or publication, then verifies the
provider delegate after restart.

## Evidence and limits

- [Live country release](/home/loukious/Android/onyx-wonder-coex-dev-20261117/mosey-activation-fix-20261117T161143423932Z/goal-working-20261117/native-capability-integration/continuation-apfree-20261118/phone-channel-unpin-v10-live-20261118T181523.544992Z/receipt-private.json): CE/cache country absence, preserved Boolean and compressed suffix, ready foreground delegate. This receipt records persistence as pending at the time of the live trial.
- [Unpinned phone channel selection](/home/loukious/Android/onyx-wonder-coex-dev-20261117/mosey-activation-fix-20261117T161143423932Z/goal-working-20261117/native-capability-integration/continuation-apfree-20261118/unpinned-channel-selection-20261118T181725.221343Z/receipt-private.json): channel 149 at 5745 MHz, no host Wi-Fi peer started, normal Wi-Fi restoration.
- [Persistent boot and first unlock](/home/loukious/Android/onyx-wonder-coex-dev-20261117/mosey-activation-fix-20261117T161143423932Z/goal-working-20261117/native-capability-integration/continuation-apfree-20261118/phone-channel-unpin-v10-post-unlock-20261118T182525.102349Z/receipt-private.json): persistent country-override absence, preserved hopping Boolean, ready foreground delegate and SELinux Enforcing.
- [Flags contract](flags-contract.json) and `native/build-cache-v10-receipt.json`: exact migration map/snapshot identities and the ARM64 helper's 49 passing cache tests. The full module passed 40 real-mksh tests; the actual rollback script also passed supported/unsupported APK guards.

The earlier provider v9/driver v15 receipts proved native multicast mDNS and
stock Owly file delivery on channel 6 while the TN pin was present. Earlier
bidirectional file receipts remain historical validation for their exact
packages. This unpin trial proves phone channel selection and cleanup, not a
new channel-6 or 5 GHz file transfer. Large files, long-duration stability,
simultaneous STA/AWDL operation, full hopping, MLO and iPhone interoperability
remain unverified.
