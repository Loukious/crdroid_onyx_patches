# Onyx KSU continuation, 2026-11-18

Driver **2026.11.18.10** and native provider **2026.11.18.9** passed persistent
boot activation with SELinux enforcing. In the preceding live native v9 trial,
Quick Share automatically disconnected Asus Wi-Fi at 5240 MHz and delivered
**40,603 bytes** to WSL on channel 6 with the exact source SHA-256, without a
manual disconnect, AP join or rate override. A separate Back-button discovery
close restored Asus/autojoin and removed the AWDL interfaces; the native service
process remained running.

Native v9 first-unlock provider registration and flag/cache checks remain pending
on the new boot. The earlier native v8 boot/first-unlock checks and controlled
**19,565-byte** AP-free transfer remain valid historical evidence.

Automatic module startup was temporarily disabled during the live trials and
has now been restored. The already loaded driver was not reloaded for those
transfers; persistent activation was checked after the later reboot.

## Validated

- QCA payload SHA256: `54cf09f0dc27ac41eb9ce1cdc4bd4b5046d374520b4d773330d3a1a580b0b1d7`.
- Running GNU build-note SHA256: `14fa9fb0293e94e01e74d2e43edcf541bad856e5b9f11631c27497d1aa070e35`.
- Current native v9 shim SHA256: `f954dac6eb4bb2768dada78b6e0b79894e24cca1b343e5ffe3d3ef81914de322`.
- Earlier native v8 shim SHA256: `1ca1a825139089328d11b767083fe688dd1d263adcc52f2e9a7c84fd825d79fb`.
- Live-transfer joint boot ID: `1d5aecab-cc68-4223-91c6-07203b7ffb7f`.
- Current persistent native v9/driver v10 boot ID: `7ef1bcdf-6cbb-4be0-9aa0-03dd47c9c655`.
- Current boot exposes the native v9 KSU overlay and matching driver build note; live Binder capability is false in `u:r:mosey_server:s0` with SELinux enforcing.
- The current boot's driver ledger contains the expected replacement payload hash.
- No ROM, kernel image or dependency module was rebuilt or replaced.
- Earlier native v8 first-unlock provider registration, foreground-service delegate and flags/cache checks passed; native v9 checks remain pending on the current boot.
- The successful live transfer trials requested no reboot and retained their joint boot ID.
- The compact RAW handler passed 7,637 actual-source ASan/UBSan cases.
- The loader passed 18 existing tests and 9 boot-lock tests, including concurrent loaders and boot races; negative controls reject the former global-lock behavior.
- The full six-patch series reproduces all 11 reviewed source files with zero fuzz. Source reproduction is separate from hardware validation.

## Fixes

The compact QCA descriptor branch previously discarded complete plaintext AWDL
unicast because its unknown-peer RAW handler was empty. The new handler verifies
helper ownership, captured header/metadata/bounds and AWDL identities, then copies
the complete original frame and FCS while retaining the original skb ownership.
This replaces a proven phone-side missing receive path. The successful AP-free
trial now confirms reception of TCP replies and completion of an outbound file
transfer on this revision.

V10 also binds reload exclusion to the boot ID. An interrupted prior-boot reload
left the old global lock present and caused the next boot hook to skip silently.
The new lock excludes concurrent same-boot reloads and preserves per-boot attempt
records without blocking future boots.

The initial live v9 attempt was interrupted at its 60-second host deadline after
multiple expensive process guard scans. A normal guarded load with a longer host
lifetime succeeded. The initial recovery reboot restored stock; the joint v10/v8
boot subsequently proved the persistent driver and native overlay identities.
The runtime scan setting must be changed through the Wi-Fi service command;
writing only the legacy global settings row did not disable scan-only operation.

## Earlier controlled native v8 AP-free file result

At 09:24 UTC, Quick Share sent `Codex_APfree_v9_20261118T062724Z.txt` to **Codex WSL**.
The host received 19,565 bytes with SHA-256
`212c794e14160faf0b69ef4fef1325b594301cbf5b357d6af4b91154e0b4b465`, matching the
independently read source bytes. Its modification time falls within the successful
trial. The phone UI showed **Sent**, and the extension logged `TransferComplete`.

Eight phone samples reported Wi-Fi enabled, no STA association, network `-1`
and autojoin disabled. Host captures contain two checksum-valid TCP handshakes
from the trial's phone address and matching acknowledgments of received replies.
No manual transmit-rate override was applied; the installed driver still uses
its reviewed destination-compatible rate handling.

The hidden Owly AP supplied the USB radio's channel context; the phone did not
join it. File selection preceded disconnection, and the same Quick Share task
was resumed so the picker could not restore Wi-Fi midway through the trial.
The saved Wi-Fi settings were restored afterward. An immediate snapshot was
still disconnected, but later evidence confirms Asus at 5240 MHz, network `3`,
supplicant `COMPLETED`, native service stopped and coexistence `active=0`.

A previous staging trial displayed “Quick Share extension keeps stopping” before
unassociation. Its cause remains unproven; a controlled-stop artifact is possible.
That earlier observation is separate from the successful transfer.

## Native v9 normal startup and graceful close

At 09:36 UTC, Quick Share sent `Codex_Normal_AirDrop_v9_20261118T093315Z.txt`
to **Codex WSL**. Independently read source and received files both contain
40,603 bytes with SHA-256
`32e999c39384b50385f1a028bace056b560a46514518f79ac14e2f7435eacd98`.
The host file was absent before observation and appeared during it; the final
phone UI shows **Sent**. All eight phone samples were unassociated, and all 60
host AP station samples were empty. Host observation records 40 foreign phone
AWDL data frames at 2437 MHz.

The controller started native/provider, opened Quick Share and selected the
fresh file while ordinary Asus Wi-Fi was initially connected. It used the Wi-Fi
helper only for inspection, with no manual disconnect, AP connection or rate
override. Native v9 reports `channel_hopping_supported=false` through Binder,
which invokes the application's ordinary STA-disconnect path. The daemon's
decoded `StartMoseyConfig` still contains `channel_hopping=true`; normal daemon
hopping is not validated by this result.

The original file-controller cleanup sent HOME and immediately force-stopped
the provider/native before waiting for reconnection. That retained receipt has
`completed=false`, `file_transfer_passed=false` and a Wi-Fi restoration timeout.
Independent source/host hashing establishes the completed file delivery; the
original orchestration failure remains preserved.

A separate discovery-only trial opened Quick Share from Asus and sent only
`KEYCODE_BACK` to close it. With no forced provider stop or manual restore,
Asus reconnected at 5240 MHz, network `3`, supplicant `COMPLETED` and autojoin
true. The `mosey0`, `wonder0` and `wondertap0` interfaces disappeared, and
the daemon logged “Subtasks exited gracefully.” The native service process
remained running. This separate close trial does not repeat the file transfer
or overwrite its earlier cleanup failure.

Driver v10 and provider v9 were then installed for persistent activation. The
new boot retains both exact payload identities, exposes the KSU native overlay,
and returns the false Binder capability under the native SELinux domain. Its
retained user state is `RUNNING_LOCKED`; historical provider log tails do not
establish new-boot first-unlock registration or cache validation.

## Still pending

- Native v9 first-unlock provider registration, flags/cache checks and repeated
  full-file validation on the current persistent boot.
- Simultaneous ordinary STA/AWDL operation; normal startup now disconnects Asus.
- 5 GHz AWDL, normal social-channel hopping and mixed-channel STA/MLO behavior.
- Reverse-direction file transfer, large files and long-duration stability.
- Direct iPhone interoperability; no iPhone is available.

The RTL8188CU USB peer is 2.4 GHz and one spatial stream; its Owly backend uses
channel 6. It cannot validate 5 GHz reception or full AWDL channel hopping. Its
local USB transmission echo alone is not proof of phone RF receipt.

## Receipts

Private hardware receipts remain in the continuation directory:
`/home/loukious/Android/onyx-wonder-coex-dev-20261117/mosey-activation-fix-20261117T161143423932Z/goal-working-20261117/native-capability-integration/continuation-apfree-20261118`.

Within that directory, the retained evidence is:

- `v10-native-v8-boot-check-20261118T064556.772402Z/receipt-private.json`: joint boot identities.
- `v10-provider-boot-validation-20261118T085419.726007Z/receipt-private.json`: first-unlock registration and flag/cache checks.
- `apfree-preselected-file-v9-20261118T092338.502284Z/`: successful trial, final UI, extension logs and host hash receipt.
- `independent-validation-success-20261118T092835.777329Z.json`: independent byte, TCP, association and cleanup review.
- `post-transfer-normal-state-20261118T092733.362443Z/wifi-before-private.txt`: completed Asus reconnection after the earlier controlled trial.
- `normal-quickshare-file-native9-20261118T093518.373495Z/`: automatic startup and exact 40,603-byte file, with original cleanup failure retained.
- `independent-native9-validation-20261118T093935.252159Z.json`: preserved partial review before graceful-close validation.
- `native9-graceful-close-20261118T094046.847532Z/`: separate normal Back close and automatic Asus restoration.
- `independent-native9-validation-success-20261118T094756.102982Z.json`: combined live startup/file and separate graceful-close review.
- `native9-persistence-boot-20261118T094649.166072Z/` and `native9-persistent-query-20261118T094711.171412Z/`: current boot activation and live Binder capability.
- `independent-native9-persistent-boot-20261118T094917.714245Z.json`: independent persistent-boot review with first unlock still pending.
- `independent-native9-current-validation-20261118T095256.501695Z.json`: combined current live-test and persistent-boot validation.

The corresponding passive host TCP receipt is
`/home/loukious/Android/airdrop-usb-wsl-20261117/v9-handshake-radio-20261118T092315Z/receipt-private.json`.
Prior failed outcomes remain preserved. The file controller's `completed` field
covers orchestration and cleanup; independent source/host hashing supplies the
separate full-file proof. The earlier controlled controller is
`test-apfree-preselected-file-v9.py`. Normal connected startup is separately
verified by `test-native9-normal-file.py`; normal close is verified by
`test-native9-graceful-close.py`. The native v9 passive host receipt is
`/home/loukious/Android/airdrop-usb-wsl-20261117/native9-normal-file-20261118T0935/receipt-private.json`.

All Android commands must use the Windows `adb.exe` and `fastboot.exe` tools.
