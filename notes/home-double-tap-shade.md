Rapidly pressing the Caffeine Quick Settings tile with the launcher underneath
can put the phone to sleep. The device log identifies the caller as
`DT2SController: DT2S: goToSleep`, immediately followed by PowerManager's
application-requested sleep event.

`DoubleTapToSleepController` globally monitors input when the Pixel Launcher
home task has focus. Opening SystemUI's notification shade or Quick Settings
does not necessarily change that task. The controller checks overview,
keyboard and bubble state, but originally omitted shade state. Its window
filter also skips trusted overlays, so task focus and that filter alone do
not establish that the user is touching the home screen.

Patch `frameworks_base/0015-exclude-shade-from-home-double-tap-sleep.patch`
adds `ShadeInteractor.isAnyExpanded` to the home-gesture eligibility check.
This state covers partial and full shade/QS expansion in both legacy and
scene implementations. Collection through `JavaAdapter.alwaysCollectFlow`
runs in the application's main-thread scope and updates monitoring whenever
the state changes. The controller reads the current StateFlow value directly
when checking eligibility rather than maintaining another cached copy.

Opening the shade now uses the existing monitor teardown to remove the input
receiver, clear the gesture detector, reset touch tracking, and cancel pending
sleep. Closing it starts a fresh detector if the other home-gesture conditions
are satisfied. The delayed sleep runnable rechecks eligibility before calling
PowerManager, including when flow delivery is pending.

Caffeine's click handling, which intentionally cycles durations on rapid taps,
is unchanged. The patch does not change the DT2S setting or the separate
status-bar, shade and lockscreen gesture handlers.

The host runner compiles the complete production Java file unchanged against
minimal input, StateFlow and main-loop models. Seventeen cases cover normal
home sleep, shade/QS already open at startup, tile taps, pending-sleep
cancellation, delayed flow delivery, gestures spanning shade transitions,
monitor cleanup, and the existing app/overview/keyboard/bubble/falsing/region/
multi-pointer/setting exclusions. The original controller passes nine and
fails eight; the patched controller passes all seventeen.

```sh
python3 -B ci/check-dt2s-shade.py /isolated/DoubleTapToSleepController.java --out /tmp/dt2s-check
```

Patch generation, exact application, repeated application, reverse checking,
and repository preflight are validated on isolated copies. These checks do not
replace a complete SystemUI/Dagger build or real device gesture testing. The
live source and running ROM build are not modified, and no phone setting,
service or installed component is changed. Deploying the fix requires a
rebuilt SystemUI/ROM.
