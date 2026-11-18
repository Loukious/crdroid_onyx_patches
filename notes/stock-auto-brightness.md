# Onyx stock auto-brightness port

The ROM carries Onyx's shipped HyperOS sensor selection, brightness conversion
and transition policy. Both stock datasets (Global 3.0.303 and China 3.0.305)
already matched the ROM's 129-point default lux/nits table. The port keeps that
table and corrects the differences in the surrounding framework behavior.

Framework patch `0018` adds separate main/rear light histories and arbitration,
the stock absolute threshold splines, landscape touch protection, rear torch
exclusion, pocket/initial response, and the stock nits-based ramp equations.
Device patch `0025` enables the policy only for Onyx. Vendor patch `0004` marks
both panel maps as linear and supplies normalized float fallback ramp rates.
The framework resource defaults to false for other products.

The default lux/nits spline stays monotone cubic. Both directions of the physical
nits/brightness mapping are linear, as stock specifies. Reduce Bright Colors
adjusted conversion keeps its stock cubic spline. Target clamping, HBM/thermal
protections and explicit strategy rate overrides remain in the display controller.
Trial 4 used Android's generic user-curve smoothing. A focused
[Global user-adjustment audit](stock-brightness-evidence/global-user-adjustment.md)
established that Xiaomi substitutes proportional scaling below the user's anchor
and an additive offset above it. That distinction was missing from the original
port. The custom affine candidate was never installed; its replacement follows
the audited Global stock algorithm and is installed as trial 5.

The copied integer fallback rates (`4932`, `3946`) belong to stock's `1..16383`
brightness scale. AOSP's `1..255` conversion clamped both to `1.0`. Explicit
panel floats restore `0.3010010988` and `0.2408130875` without changing Android's
global integer brightness API. Ordinary stock animations integrate in linear
brightness using the verified stock per-VSYNC Euler step; explicit Android
custom-rate overrides retain their native HLG units.
Intermediate property writes follow stock's 14-bit equality check while retaining
fractional progress. Android's exact final-target and animation callback contract
is preserved.

The [static profile](stock-brightness-evidence/stock-profile.json),
[stock table](stock-brightness-evidence/default-lux-nits.csv),
[curve comparison](stock-brightness-evidence/curve-comparison.json) and
[artifact identities](stock-brightness-evidence/artifact-identities.json) record
the reference defaults. The original static audit/decompilation snapshots are
retained locally at
`/home/loukious/Android/onyx-auto-brightness-audit-20261114`.

## Reproduce checks

Generate only this feature's patches, using temporary indexes and scoped paths:

```sh
python3 -B ci/gen-stock-brightness-patches.py /path/to/rom --out /path/to/patches
```

`gen-patches.sh` invokes the same generator. It filters shared resource/controller
hunks so unrelated local features cannot enter this patch. The normal `apply.sh`
patch loop discovers the three new patches automatically and reverse-checks
them on a tree where they are already applied.

Run the actual lux engine/ramp code and JUnit tests using the ROM's JUnit jars:

```sh
python3 -B ci/check-stock-brightness.py /path/to/rom --out /tmp/brightness-check
```

The host runner records input hashes and compile/run logs. Ramp API stubs are
kept under `ci/brightness/ramp-stubs`; `Spline` and `BrightnessUtils` are actual
ROM sources. It also checks all 129 curve points, 34 threshold anchors and both
panel conversion/ramp configurations against the retained stock profile. The
JUnit checks cover filtering/debounce/protection and ramp behavior.
They do not execute Android sensor/input registration or prove physical output.
Mapping, display-config and platform adapter tests live in the framework's
`displayservicetests` target and require separate Android validation.

Build the production resource/service/overlay modules and the display test APK
with the current Android 17 product release configuration:

```sh
SOONG_GOMEMLIMIT=20GiB LUNCH=lineage_onyx-cp2a-userdebug JOBS=3 ci/local-compile-check.sh \
    /path/to/rom framework-res services.core FrameworkOverlayOnyx DisplayServiceTests
```

The optional `SOONG_GOMEMLIMIT` setting bounds Soong's Go heap target for the
local build; it does not change ROM source or runtime brightness behavior.
Building `DisplayServiceTests` verifies test compilation. Executing that APK
requires an Android device or suitable test environment.

Validation on 2026-11-14 passed 75 host JUnit tests, the retained stock-profile
checks, ordinary patch application/reversal and deterministic regeneration.
Focused compilation of all eight changed production Java files, actual framework
resource generation/linking and the complete Onyx overlay passed using real
cached dependencies. Six Android test classes also compiled against actual
Android classes; these tests were not executed. The full Soong module build was
stopped during graph generation under local memory pressure, including after a
`SOONG_GOMEMLIMIT=20GiB` attempt. Its completion and the DDC/DPC instrumented test
build remain separate checks before a ROM release. See the
[validation record](stock-brightness-evidence/validation.json).

The retained [validation record](stock-brightness-evidence/validation.json) has
38 lux and 37 ramp host tests passing. All three patches apply with ordinary
Git checks to the pre-port source baseline, reproduce the current source bytes,
reverse cleanly on the actual ROM, and regenerate byte-for-byte identically.
These are host/source checks; the Android build and device behavior need their
own results.

## Scope and remaining device validation

This ports verified shipped static defaults. Xiaomi's cloud personalization is
not reproduced: the shipped game touch-cover list starts empty, and the separate
brightness step mode is disabled. No invented all-games classification is used.
The adapter uses one monotonic elapsed sensor time base and translates scheduled
deadlines to Android handler uptime. It rejects invalid/out-of-order samples and
permits assistance-only initialization when the main sensor is unavailable.
Android supplies lifecycle, user adjustment and animation callback APIs. Xiaomi's
daemon warm-start cache and cloud user data are not copied into this ROM.

Read-only checks on the connected phone confirmed main light type `5`, rear
assistance `33171055`, non-UI/pocket `33171027`, and active panel
`4630947173316895379`. Before the trial, the installed Android 17 ROM reported
cubic nits/brightness interpolation and all four ramps as `1.0`, corroborating the
conversion/ramp defects. Only these configuration facts are retained in the
[device configuration record](stock-brightness-evidence/device-configuration.json);
full device dumps are kept out of this patch repository.

On 2026-11-14, the build-specific KernelSU trial was installed on Onyx Android 17,
SDK 37, incremental `1794595788`, and accepted after a successful reboot. It
overlays the patched `services.jar` and both panel XML files. The awake display
dump confirmed linear conversion, corrected ramps, valid ambient lux, and active
rear sensor assistance, pocket and touch monitoring. A subsequent read-only check
confirmed the accepted state, matching mounted and health-verified boot markers,
no failure or disable marker, enforcing SELinux, and all three mounted payload hashes.
The initial trial exposed a manual/auto restart defect on 2026-11-14: Onyx's
on-change main ALS could deliver a cached reading timestamped before registration.
The port rejected that initial reading and used rear-only lux until the main
reading changed. The corrected adapter accepts that first cached observation at
the current sensor time; subsequent stale, out-of-order, invalid and future samples
retain their rejection rules. Six host regressions and Android lifecycle tests
cover this behavior. A retained learned preference at zero lux also requested
maximum SDR brightness; its state was backed up locally before resetting the
brightness configuration. Trial version `2026.11.14-trial.2` includes the sensor
correction. It was installed, booted with enforcing SELinux, and accepted after
three repeated minimum-manual-to-auto transitions. Each transition initialized
one main ALS sample at registration time, with ambient lux `5.3916254`, target and
actual brightness `0.02017211`, and no user-point anchor. Previously the target
was `0.49951124` at zero lux. The revised trial remains enabled with automatic
brightness on. All 81 host tests pass; Android lifecycle regressions compile.
Runtime receipts and preserved trial.1 artifacts remain in the local work folder. The module ZIP, receipt,
compatibility checks and device dumps are retained locally under
`/home/loukious/Android/onyx-stock-brightness-ksu-20261114`; the
[trial instructions](../tools/onyx-brightness-ksu/README.md) describe its guards.
This package requires the exact build and baseline hashes it was created for.

The trial confirms runtime startup and sensor registration; physical luminance
equivalence to stock remains unmeasured. The production ROM still requires a
completed full build. Before calling it measured stock-equivalent, verify front
and rear sensor coverage, torch release, pocket exit, landscape touches,
indoor/outdoor changes, user adjustment and Reduce Bright Colors on the device.
Retain HBM and thermal
limits during those checks. Device commands must use Windows
`adb.exe`/`fastboot.exe`, including from WSL; the local executable is
`/mnt/d/platform-tools/adb.exe`.

Continued device checks reproduced a separate Quick Settings input issue. Three
exact manual-brightness-`1` to auto transitions, with three seconds of settling
before the A/M tap, all raised framework brightness from `0.0` to `0.008805807`.
The current learned point at lux `4.58075`, brightness `4.4028836E-4`, remained
unchanged. Immediate A/M taps after a slider drag were ignored in two of two
attempts; a 100 ms additional delay passed one of two, while 250, 500 and 1000 ms
delays each passed two of two. Input-command overhead means these are coarse
timing checks. The phone remained in manual mode after an ignored tap, and
enabled auto normally on a later tap.

`QSFragmentCompose` blocked new pointer events while the brightness mirror was
showing, including the legacy shade's 140/200 ms return animation. Framework
patch `0019` now reads the actual drag state at the first DOWN of each gesture
using a stable pointer handler. It keeps that decision through UP, allowing the
original slider drag to complete and accepting a mode tap immediately after
release. The handler remains installed throughout the animation, so no UI frame
is needed to remove an old consumer. Trial 3 exposed that frame-dependent gap and
was rolled back before acceptance; trial 4 carries the stable handler.

The same patch registers brightness UI intents synchronously, waits for preceding
suspending brightness conversions, and queues repository mode changes together
with brightness writes. This preserves slider-release/mode-tap order. It carries
five production files and three Android regression test files. The mirror test
freezes the Compose clock while changing drag state and checks the actual
production gate; another regression checks that an allowed drag reaches release.
The patch generator reproduces all eight files, and the other three stock
sensor/configuration patches remain byte-identical. Production Kotlin compilation
passed against 767 actual cached dependency jars. The added Android Compose
regressions have not been executed.

The exact cached SystemUIGoogle R8 edge was recovered without changing Soong
outputs. Its baseline reproduced all three installed DEX files byte for byte.
All 205 compiled owner classes were included in the modified input; 84,313
unrelated input entries were preserved. The rebuilt resources match both baseline
and cache exactly, and all 4,556 original non-DEX APK entries remain unchanged.
The APK passes alignment and platform signature verification. Exact device
linkage checks cover 4,631 member references, including the new top-level gesture
helper and 46 incoming references from unchanged classes, with no missing members,
uncovered owners, illegal direct accesses or visibility regressions.

Trial `2026.11.14-trial.4` was installed and accepted on the same Onyx build after
all four mounted hashes, SELinux labels, enforcing mode and current-boot framework
and SystemUI service health passed. On the unlocked phone, five immediate
slider-release-to-Auto sequences passed with no added delay between input
commands. Three exact manual-brightness-1-to-Auto sequences raised actual brightness
from `0.0` to `0.023045078` at ambient lux `6.358375`, with reason `automatic` and
no maximum jump. The short-term learned point was absent after the reboots; no
learning reset was issued during this UI deployment. Rear assistance, pocket and
touch monitoring were registered. Auto remains enabled, torch off, QS collapsed,
and temporary stay-awake and debug logging changes are restored. The
[SystemUI runtime record](stock-brightness-evidence/systemui-runtime-checks.json)
summarizes these results. Full traces, interrupted lock-screen runs and rejected
trial 3 artifacts remain in the local work folder. Broader lighting and physical
luminance equivalence remain unmeasured.

A subsequent report of maximum manual brightness staying high after Auto was
captured with reason `automatic`, valid front lux `3.861375`, no temporary
brightness override, and an existing user point at lux `3.8613749`, brightness
`0.49951124`. Both settled manual-maximum and manual-halfway transitions returned
to that same pre-existing point. History records it as an Auto `user_set`
adjustment at device time `21:08:42.667`, followed by a Manual-mode event at
`21:08:43.250`; the original physical input mode cannot be established from the
retained logs. This proves retention of a learned ceiling target rather than a
sensor-settling delay, but does not prove a newly misclassified manual write.

After an ordinary restart, with no explicit learning reset, the short-term point
was absent. Three framework maximum-to-Auto checks, an immediate QS maximum drag
to Auto, a settled manual value `128` (actual `0.5`) to Auto, and six rapid
Auto-to-Manual-to-maximum-to-Auto sequences all returned to target/actual
`0.015280787` at lux `4.0150003` by one second, without adding a user point.
The retained adjustment was initially `0.48476738` after restart and was rewritten
to the mapper's `0.0` by normal Auto processing. No source or module change was
installed for this follow-up. A possible asynchronous brightness-write provenance
gap was identified in source, but was not reproduced; no speculative model reset
or framework patch was applied. The
[maximum-to-Auto follow-up](stock-brightness-evidence/max-auto-followup.json)
retains the scope and uncertainty. Auto remains enabled with the trial 4 module.

The external-light check confirmed rear selection in all twelve captures with
front lux `0`, rear lux approximately `6.0913796`, and auto target `0.008805807`.
The torch UI check recorded on/off policy updates and recovery without a maximum
brightness jump. Auto was left enabled, torch off, Quick Settings collapsed, and
auto-brightness debug logging disabled. The
[continued runtime record](stock-brightness-evidence/continued-runtime-checks.json)
summarizes these checks; raw traces and the control script remain in the local
trial folder's `sensor-time-fix/continued-checks` directory.

Trial 5 replaces generic user-point smoothing with the verified Xiaomi Global
algorithm. The rejected affine candidate was never installed. Sixty-one curve
cases and 636 outputs match unchanged shipped methods and shipped splines bit
for bit. Production compilation, nine Android regression-method compilations,
independent DEX/API/resource checks, and ordinary patch reversal checks passed.
Android instrumentation was not run.

Trial 5 is installed and accepted. The device API and normal Quick Settings
tests preserve an interior Auto preference through Manual/Auto toggles. With
the saved point at `6.82575` lux and brightness `0.077828355`, external front
light raised detected lux to `30.687443` and current brightness to `0.12190067`.
Shading the front lowered lux to zero and current brightness to `0.0040913476`.
The point and cached baseline remained unchanged throughout. All four mounted
hashes, enforcing SELinux, current-boot framework/SystemUI health, and absence
of relevant crashes passed after testing. Auto remains enabled, QS is collapsed,
torch is off, and temporary stay-awake is restored. These are Android-reported
brightness values, not external photometer readings. The
[Global adjustment validation](stock-brightness-evidence/global-user-adjustment-validation.json)
records the installed hashes and test scope; raw logs are under
`/home/loukious/Android/onyx-stock-brightness-ksu-20261114/global-learning-trial5`.
The existing Android model lifecycle is retained; this change does not port
Xiaomi's separate cloud-dependent reset policy.

To restore the base files, use the KernelSU module's Action button, which disables
the trial and reboots, or run:

```sh
/mnt/d/platform-tools/adb.exe shell su -c \
    '/system/bin/sh /data/adb/modules/onyx_stock_brightness_test/rollback.sh --reboot'
```
