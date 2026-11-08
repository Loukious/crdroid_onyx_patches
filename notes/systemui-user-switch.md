# SystemUI crashes and authentication messages after user switches

The November 8 device capture recorded two SystemUI crashes at epochs
`1794108042.771` and `1794108219.231`. Both threw `Cannot round NaN value` from
`BackgroundBlurAlphaSync.sync()` during pre-draw. These were SystemUI process
restarts within one kernel boot. Earlier full-device reboots remain unexplained.

## Quick Settings expansion and blur

Patch `0016-fix-qs-expansion-and-blur-nan.patch` fixes a concrete NaN producer:
`QuickSettingsControllerImpl.computeExpansionFraction()` divided by
`mMaxExpansionHeight - mMinExpansionHeight` even when both were zero. The QS
fragment publishes expansion before its first layout. Its expansion flows into
both the keyguard root and device-entry icon alpha, then the blur synchronizer.
The host reproduction reaches the same exception through the icon alpha formula.
The historical crash stacks do not record the original QS height values, so
they cannot identify this as the sole producer of the captured invalid alpha.

An empty or reversed expansion range now returns collapsed (`0f`), and a valid
range is clamped to `[0, 1]`. Expansion recovers normally after layout. The blur
synchronizer also treats a non-finite effective alpha as transparent for that
frame, recomputing normally on the next frame. This prevents another invalid
view alpha from terminating SystemUI without leaving QS's invalid producer intact.

Source commit: `cd36254166959` on `Loukious/frameworks_base`,
`secure-spaces-auth-duress`.

## PIN reason after switching users

Patch `0017-scope-bouncer-auth-messages-to-selected-user.patch` corrects two
message-selection defects. The initial message now reacts to user selection
even when both users use the same credential type. Until that user's auth flags
arrive, it displays a plain credential prompt instead of reusing another user's
restart/lockout reason. Matching `STRONG_AUTH_REQUIRED_AFTER_LOCKOUT` flags now
produce the existing "required after too many attempts" message independently
of the fingerprint/face sensor's current lockout flag.

The capture showed user 0 with flags `0x8` (after lockout), while another user
had `0x9` (after boot plus lockout). Failed credential checks preceded lockout;
user 0's flags later cleared after credential entry. It did not show a new
after-boot requirement for user 0. The host tests reproduce stale restart text
when user selection and auth flags arrive in either order. They establish the
source defects, but do not prove which displayed frame the user saw historically.

This changes messages only. It does not clear authentication flags, reset failed
attempts, alter credential routing, bypass lockout, or enable fingerprint during
a real primary-auth requirement. A previous successful PIN entry does not exempt
a user from a later lockout.

Source commit: `7811ee9b072ce` on the same source branch. Both changes are general
SystemUI patches; the existing Secure Spaces export `0009` remains pinned to its
audited source snapshot.

## Validation and deployment

- 40 host cases pass; the original revision passes 22 and fails 18. Coverage
  includes zero/equal/reversed QS heights, normal expansion, layout recovery,
  invalid ancestor/transition alpha and recovery, the QS-to-icon-blur path, and
  both user/flags delivery orders for PIN, pattern and password. Real reboot
  message priority and clearing lockout are preserved.
- The complete changed Kotlin classes and Java QS controller compile against
  the ROM's existing Android dependency jars, with output outside the ROM tree.
- Ten Android regression test methods are added. They have not been run on
  Android; the host harness extracts the QS method and initial bouncer flow,
  and compiles the complete blur class, auth flags and message-string mapping
  against modeled Android views/services. It does not test the full SystemUI
  lifecycle, Dagger graph, native rendering or physical fingerprint sensor.
- Patch application, reverse checking and exact resulting source comparison
  pass in an isolated fixture. Repository preflight checks pass.
- The import checker now recognizes Kotlin extension properties such as
  `Kosmos.fakeShadeRepository`; its old simple-name expression falsely reported
  that existing test fixture as missing.

Run the focused host regression suite with:

```sh
python3 -B ci/check-systemui-user-switch.py /isolated/frameworks/base \
  --kotlin-home /path/to/android/external/kotlinc --out /tmp/systemui-user-switch
```

These fixes require a rebuilt and installed SystemUI/ROM and device verification.
The active ROM checkout/build and the phone installation were not changed.
Unattended crash capture remains active for unexplained full-device resets.
