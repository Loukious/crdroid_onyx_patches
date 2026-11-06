# nicmd netlink permission migration

With Android's `netlink_xperm` policy capability enabled, Linux 6.13 and later
check explicit netlink message permissions. The Onyx vendor policy still gave
`vendor_nicmd` legacy route read/write/readpriv/getneigh and XFRM read/write
permissions. Its explicit route allow-list contained only unprivileged queries,
so `RTM_GETLINK` and `RTM_NEWLINK` failed with SELinux EACCES.

The startup failure prevented creation of `rmnet_data*` and `r_rmnet_data*`.
During modem WDS connection indications, nicmd then repeatedly tried to bring
up a missing reverse-data interface and reported failure to the modem. The
resulting QRTR traffic repeatedly woke the phone from suspend.

Patch `0020-nicmd-netlink-xperms.patch` creates
`sepolicy/vendor/vendor_nicmd.te`. It adds the 68 route and 25 XFRM message IDs
covered by the existing legacy permissions, scoped to this one domain and its
own sockets. The lists come from the kernel's legacy `nlmsgtab.c` tables; no
unassigned message IDs or unrelated domains are granted. The old grants remain
for older kernels. The generator includes the new file, and the normal patch
loader discovers it in filename order.

## Validation on 2026-11-06

The phone was running the matched temporary 6.18.38 kernel with the separate
timerfd/freezer correction. SELinux stayed enforcing throughout the tests.

* Granting only GETLINK removed its denials but retained the WDS retry loop.
  A daemon restart exposed the earlier NEWLINK denials.
* Applying the full migration and restarting nicmd created three forward-data
  and four reverse-data interfaces. The connected capture had no netlink
  permission errors and the periodic WDS `0x8e` loop stopped.
* The subsequent unplugged capture retained 98 complete sleep spans with zero
  buffer overruns/drops, zero WDS `0x8e` indications, zero QRTR first wakes,
  and zero netlink permission failures. Median sleep duration was 1.640443 s,
  versus 0.246270 s in the earlier capture. These are separate capture windows,
  not a controlled battery-life benchmark. Remaining logged IRQ wakes were
  mostly WLAN_CE_2.
* The original live policy was restored after testing and verified by comparing
  the complete decompiled policy. No partition was flashed. The new source rule
  is intended for the next ROM build.

This fixes the demonstrated modem setup and retry mechanism. It does not
suppress WLAN firmware refusals: the earlier capture reproduced one reason-7
(roaming busy) refusal followed by a positive ACK 2.108924 seconds later. The
corrected-policy capture had 167 positive ACKs and one reason-0 refusal. It does
not establish that every future firmware-busy response will disappear.

The patch clean-applies, reproduces the source file byte-for-byte, reverse-checks
against the local ROM source, and passes generator shell syntax checks.

Focused policy compilation passed using the ROM's cached preprocessed policy
from November 4–5 plus the exact new rules, expanded with the current ROM's
`nlmsg_defines`. Both baseline and candidate passed vendor CIL compilation,
`checkpolicy` neverallow assertions and `sepolicy-analyze neverallow -w`.
Decompiling the resulting complete policies confirmed that only nicmd's own
route/XFRM grants changed, with the same semantic delta as the phone-tested
candidate. The expanded lists exactly match all 68 route and 25 XFRM IDs.

A fresh Soong invocation for `vendor_sepolicy.cil sepolicy_tests` initially
stopped before policy compilation because the direct command omitted
`LINEAGE_BUILD=onyx`. That skipped `BoardConfigLineage.mk` and consequently
Qualcomm's WLAN namespace setup. This was a validation-command error, not a
demonstrated ROM configuration defect.

Repeating the check through `ci/local-compile-check.sh`, which sources
`build/envsetup.sh` and runs `lunch lineage_onyx-bp4a-userdebug`, restored both
Qualcomm WLAN namespaces and passed that failure point. Soong then stopped
because Canvas and Etar request SDK 37 but this checkout cannot resolve
`sdk_public_37.0_system_modules`. Neither attempt reached policy compilation.
No WLAN or application build settings were changed. The focused checks validate
the rule against cached policy; they do not replace a fresh build. Also,
`sepolicy_tests` is the test executable target; the genrule that runs it is
`sepolicy_test`, which has not run here.

Detailed receipts, commands and input hashes are saved locally under
`/home/loukious/Android/konoha-wlan-wow-20261106/root-cause-052811/`:
`rom-nicmd-focused-validation/report.json`, `rom-nicmd-patch-validation.json`,
`nicmd-netlink-migration-review.json` and `migration-sleep-analysis.json`.
