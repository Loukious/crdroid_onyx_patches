# Onyx device validation, 2026-11-17

Revision 4 was installed through KernelSU Next on Onyx, Android SDK 37,
GMS 26.46.30 (`264630035`), with the existing Mosey APK version code 60715.

Artifact: `out/onyx-mosey-gms-20261117-v4.zip`

SHA256: `ac91eb00fe355523c94bf92f3db9170d899efdc25b45109b73989187a4d187d2`

Seventeen host tests passed, including actual mksh execution and the PID
delimiter regression found on Android. The installed service passed its live
provider/delegate check before reboot. A real reboot changed boot ID from
`7263f550-9a23-45e5-90cc-8f44818f3b3d` to
`ffd54f44-f58d-4447-b0f1-5f13dee6606d`.

After first unlock, without manually invoking the module service:

- The installed module remained version `2026.11.17.4` / `2026111704`.
- CE inspection returned `true` for Nearby flag `45704091`; DE returned
  `not-ready` and was skipped without creating a Nearby registration.
- GMS's persistent API service listed provider `204177216` for
  `com.google.android.mosey`, version 1.
- The live provider and foreground delegate shared PID 11239. The module
  logged `Mosey provider ready` automatically.
- The policy helper reported `updated` during early boot and `already present`
  during late startup. Decoding the loaded policy confirmed only the required
  base NLMSG permission and NLMSG message 19 for `mosey_server`; the incorrect
  route-socket ioctl 19 grant was absent. SELinux remained Enforcing.
- The original, absent-flag CE backup was seeded before startup using SQLite's
  coherent backup API. State directory mode was 0700 and baseline/version files
  were 0600. No DE rollback baseline was seeded because DE was not changed.

The policy grant does not make the current radio implementation operational.
A disposable text SEND discovery request still produced vendor `EBUSY` and a
down `wonder0`, with no discovery or transfer demonstrated. Preboot return and
instruction probes established DP support true, firmware synchronous deletion
support true, TESTMODE false, nonnull STA vdevs 0/1, and both direct CM connected
checks false. Owner count zero produced `EOPNOTSUPP`, which startup converted to
`EBUSY`. After reboot, more focused probes compared object identity and timing:
the same vdev-0 MLME/CM context was connected outside native startup, then
disconnecting at uptime 556.259, disconnected at 556.297, and disconnected for
all native starts at 556.797–572.544. Both MLME/CM contexts remained nonnull.

The application log explicitly records disabling autojoin, then `Disconnect
Wi-Fi because DBS is not supported`, then a disconnected callback before native
startup. Android's explicit Wi-Fi disconnect retains the STA interface up/open.
Consequently neither the connected-owner coex path nor standalone-down-STA path
accepts the requested lifecycle. This is an app/native handoff incompatibility;
the direct CM connected-state checks and firmware capability checks are working.
No connected-state fallback, capability spoof, or concurrency/regulatory guard
removal was applied.

A subsequent one-shot standalone handoff test observed the APK disconnect and
requested only `wlan0` down during the vendor retry window. Its userspace
30-second restoration watchdog intentionally rebooted the phone when the trial
did not finish. Recovered previous-boot kernel logs from OnyxCrashCapture show
successful vdev-0 deletion at epoch 1794937915.129 and vdev-1 deletion at
1794937915.158, about 29 ms apart. The next native worker returned
`EOPNOTSUPP` at 1794937915.233, `EAGAIN` at 1794937915.654, and
`EOPNOTSUPP` again at 1794937917.043. Firmware idle shutdown began at
1794937915.494, firmware was ready after restart at 1794937917.021, and
another idle shutdown began at 1794937917.294. STA teardown therefore reached
successful vdev deletion; a STA-stop deadlock was not established. Native
startup/cleanup or the following interface query may have stalled during that
idle shutdown/restart race. No standalone startup or interoperability was
proved. Boot reason reported a normal reboot and pstore was empty. After this
restoration, `wlan0` was up, the
original saved Wi-Fi connection had recovered, external autojoin was enabled,
and `stay_on_while_plugged_in` was restored to its original value 0. All private
trace probes were absent. No persistent interface-handoff workaround was added.

The USB host receiver is separately prepared under
`/home/loukious/Android/airdrop-usb-wsl-20261117`: RTL8188CU `0bda:8176`, exact
WSL kernel driver and shared-namespace firmware, Owly v0.4.3, channel 6, receiver
name `Codex WSL`. Driver/radio startup passed; this untested 2.4 GHz adapter has
not completed an AirDrop transfer with the phone. Its README provides bounded
restart and rollback commands.

Evidence is retained under
`/home/loukious/Android/onyx-wonder-coex-dev-20261117/mosey-activation-fix-20261117T161143423932Z`,
including `module-v4-install-receipt.json`, `module-v4-postboot-early.stdout.txt`,
`module-v4-postboot-late.stdout.txt`, `module-v4-postboot-services.stdout.txt`,
`module-v4-postboot-gms-providers.stdout.txt`,
`module-v4-postboot-policy-verified.json`, and the scoped trace/cleanup receipts
under `coex-diagnosis`, especially `postboot-cm-context-comparison.json` and
`postboot-cm-cleanup-receipt.json`. Recovered trial excerpts are retained in
`handoff-previous-kernel-window.stdout.txt` and
`handoff-previous-kernel-relevant.stdout.txt`; the post-trial probe and driver
baseline is in `handoff-leftovers-and-tx-baseline.stdout.txt`.
Database backups and full device dumps are private
runtime evidence and are not included in the module ZIP.

## Version 5, applied without a reboot

Artifact: `out/onyx-mosey-gms-20261117-v5.zip`

SHA256: `4263733cb0d05be44721cb0f10e520250b91d62bf76a5f075481cb8c615e7f5b`

The package includes the runtime-validated ARM64 Wonder capability adapter.
It was installed through KernelSU Next into `modules_update`; both the staged
library and metamodule image carry `system_lib_file`. The current boot uses
a reversible native-library bind. The package overlay takes effect on the next
normal reboot, whose version-5 automatic startup has not yet been exercised.
No ROM image was rebuilt or flashed for this version-5 device update.

A read-only Java Binder probe in the normal `mosey_server` domain decoded
interface version 2 and hash `fd5f0a3ddad1085d5e231bafbe06f6feb9b80f58`,
plus a 12-byte stable Parcelable with hopping=true. The real nl80211 query
reported HBS=false, NSS=2 and max-switch-time=12000000 us. SELinux remained
Enforcing, and no sysfs or generic-netlink permission was added. All original
Binder calls forward to the unchanged native service.

All 28 host module tests pass; clean source-overlay replay passes twice; the
ZIP reproduces byte-for-byte. The running module service reported CE app flags
changed, DE unchanged, and provider/delegate ready at PID 25235. Independent
read-only verification confirmed the two typed CE overrides, a 263-country map
with TN6/PS44, links to committed/latest states, private independent baselines,
and the original version-4 Nearby baseline byte-identical to its saved hash.
Native capability querying remained successful after the flag update.

Evidence is under `goal-working-20261117/native-capability-integration`,
including `query4-after-flags.txt`, `module-v5-final-live-service.txt`,
`final-module-tests.txt`, `final-package-validation.json`, and
`targeted-source-build-receipt.json`. Canonical REA APK evidence is in the
sibling `rea-apk/evidence-index.json`. Radio discovery and transfer are pending
the channel-6 runtime trial.
