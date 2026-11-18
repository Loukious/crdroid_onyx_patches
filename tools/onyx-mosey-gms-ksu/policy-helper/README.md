# Mosey route-message policy helper

The measured Mosey denials require `RTM_GETLINK` (18 / `0x12`) for interface
queries, `RTM_SETLINK` (19 / `0x13`) to bring `wonder0` up, `RTM_NEWNEIGH`
(28 / `0x1c`) to add neighbors, `RTM_DELNEIGH` (29 / `0x1d`) to remove them,
and `RTM_GETNEIGH` (30 / `0x1e`) for neighbor queries. GETNEIGH and the subsequent
NEWNEIGH denial were measured in the v7 adapter/v3 Wonder RX-header trial;
DELNEIGH was then denied during peer expiry. All were measured with SELinux
Enforcing. The helper retains the existing live policy and adds only those
five NLMSG extended permissions for
`mosey_server self:netlink_route_socket`, plus the necessary base `nlmsg` bit.

An existing NLMSG grant keeps its unrelated bits, selectors and driver records.
Permissions split across multiple NLMSG records are combined when checking
whether all five messages are already allowed. The historical KernelSU parser
mistake is repaired only when the matching ioctl record contains exactly
SETLINK 19 and no other bit. Other ioctl records remain intact.

The source policy counterpart is
[`mosey.te`](../../../assets/onyx-mosey-source/files/sepolicy/mosey.te).
The module's helper build uses existing AOSP libsepol archives, Clang and an
Android NDK sysroot. It does not rebuild the ROM.

```sh
python3 tools/onyx-mosey-gms-ksu/policy-helper/build-helper.py \
  --rom /home/loukious/Android/custom-rom \
  --ndk /home/loukious/Android/Sdk/ndk/28.2.13676358 \
  --baseline-policy /path/to/saved/sepolicy-before.bin \
  --ksud-policy /path/to/saved/sepolicy-after-ksud.bin \
  --loaded-policy /path/to/saved/sepolicy-loaded-corrected.bin \
  --link-policy /path/to/saved/sepolicy-current-getlink-setlink.bin \
  --getneigh-policy /path/to/saved/sepolicy-current-getlink-setlink-getneigh.bin \
  --newneigh-policy /path/to/saved/sepolicy-current-getlink-setlink-newneigh-getneigh.bin \
  --output tools/onyx-mosey-gms-ksu/policy-helper/onyx-mosey-nlmsg-arm64 \
  --receipt tools/onyx-mosey-gms-ksu/policy-helper/build-receipt.json \
  --workdir /path/to/offline/verification
```

`--loaded-policy` accepts the previously saved SETLINK-only policy. Its upgrade
must change exactly that NLMSG record to include GETLINK and all three neighbor messages.
`--link-policy` accepts the current GETLINK/SETLINK policy and must change exactly
that NLMSG record by adding the three neighbor messages. `--getneigh-policy`
accepts the saved 18/19/30 policy and must add NEWNEIGH 28 and DELNEIGH 29.
`--newneigh-policy` accepts the current 18/19/28/30 policy and must add only
DELNEIGH 29. The baseline test
checks the base-permission insertion, and the KernelSU test checks the exact
selector repair. Every decoded CIL record is compared, and each output must be
byte-identical after repeated application.

[`test_policy_nlmsg.py`](test_policy_nlmsg.py) also exercises a complete grant
of 18/19/28/29/30 split across records, combined and split 18/19 grants missing
28/29/30, a partial grant with unrelated low/high-word bits and driver/ioctl records,
GETLINK-only and GETNEIGH-only grants, and an unrelated multi-bit ioctl record.
An exact SETLINK-only ioctl record must survive when a correct NLMSG record
already exists. The complete split grant must remain byte-identical on its first pass.
These tests run the compiled production helper against real policy images with
offline fixtures; they do not exercise the device's policy loader.

The build receipt records the executable, source, test script, libraries,
headers and compiler hashes, compilation arguments, exact record deltas and
idempotence results. The ARM64 PIE build verifies every LOAD segment has Android
16 KiB alignment and congruent file/virtual offsets. Device startup uses `--apply`; that path retains the
existing enforcing-state, serialization, concurrent-policy-change and loaded
image validation checks.
