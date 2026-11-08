# Cancelled lockscreen swipe leaves the keypad stuck

The November 8, 2026 device trace captured the reported sequence: start swiping
up from the lockscreen, reverse before completing the swipe, then release.
The keypad disappeared and immediately reopened. Subsequent edge gestures
reached the NotificationShade Back callback with `triggerBack=true`, but the
keypad stayed open.

At 02:56:49.105 UTC the manual `LOCKSCREEN -> PRIMARY_BOUNCER` transition was
canceled and a return to `LOCKSCREEN` began. At 02:56:49.118 a delayed legacy
bouncer repair called `show(false)` and forced expansion to `0f`, reopening
the keypad. The same sequence appeared in two later partial-swipe attempts.

This is in the custom legacy bouncer bridge carried by Secure Spaces patch
`frameworks_base/0009-secure-space-entry-coordinator.patch`. The bridge runs a
background collector and hands UI work to the main dispatcher. Filtering a
STARTED/RUNNING event before that handoff did not establish that the transition
was still active when the UI work ran. It also forced expansion to `0f` on
every event, fighting the actual swipe position. The cancelled swipe had
already expanded the shade to `1f`; Back's normal request to expand that shade
therefore could not drive another keypad hide animation.

The repair now reads the authoritative transition and current shade expansion
on the main thread. It only updates a manually driven
`LOCKSCREEN -> PRIMARY_BOUNCER` transition. It samples expansion after the
dispatcher handoff or a suspended transition start, and never queues a show
at the hidden endpoint. Animated bouncers retain their expansion and scrim
ownership. The prior recovery for an invisible legacy credential view after
biometric dismissal remains covered, including a stale showing-soon flag.

The constructor again accepts `mainDispatcher`, matching the existing Kosmos
fixture. Gesture recognition, predictive Back, credential routing, SIM security,
and authentication requirements are unchanged.

Source commit:
[`144707dd6f39b519941486cf812f1fcd65734fbc`](https://github.com/Loukious/frameworks_base/commit/144707dd6f39b519941486cf812f1fcd65734fbc),
on `secure-spaces-auth-duress`. The generator pins that source snapshot and
exports the correction inside `0009`; no stacked patch modifies the same hunk.

Validation:

- The host runner compiles the complete production interactor unchanged with
  real coroutines and StateFlow. Controlled main/background queues reproduce
  delayed UI delivery, cancellation before reversal starts, transition
  replacement, animated ownership, a suspended manual start, normal completion,
  reopening, scene mode, and the previous invisible-bouncer recovery. The
  original passes 3 and fails 10; the corrected source passes all 13.
- The production interactor and its unchanged parent compile with Kotlin 2.2
  targeting JVM 21 against the current Android SystemUI build's 769 dependency
  jars. Compilation outputs are outside the live build tree.
- Five Android regression tests are included in
  `FromLockscreenLegacyBouncerTest`. Instrumentation execution and a complete
  SystemUI/Dagger build remain pending.
- Exact patch application and reverse checking pass. All 23 files exported by
  `0009` match the pinned source commit byte for byte. Repository preflight
  passes, including the 18 upstream-guard tests.

```sh
python3 -B ci/check-bouncer-back.py \
  /isolated/FromLockscreenTransitionInteractor.kt \
  --kotlin-home /path/to/android/external/kotlinc \
  --out /tmp/bouncer-back-check
```

The fix requires a rebuilt SystemUI/ROM and device verification. This work did
not alter the running ROM source, build, phone software, or authentication
settings. Private device captures remain outside this repository.
