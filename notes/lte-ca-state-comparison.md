The phone logs exposed an ordering defect in Evolution X's per-SIM
“Carrier aggregation” feature. The previous service state already carries
`mForceLteCA`, while a newly polled state has that field reset to null.
`pollStateDone()` originally applied the override after ratcheting, equality
checks, and the decision to notify service-state listeners.

With the switch enabled, this makes the RAT-family check see LTE_CA in the
old state and LTE in the new state even when their network-registration
aggregation flags have not changed. Both enabled and explicitly disabled
overrides can also make `ServiceState.equals()` report a change on an otherwise
unchanged poll. The saved audit identified 13 warnings involving this override
mismatch; five printed state pairs differed only in their display-override
fields. The source matches upstream Evolution X telephony revision
`35d106ebee94ca883806c0876302fdd3eb06bab7`.

`frameworks_opt_telephony/0001-apply-lte-ca-override-before-state-comparison.patch`
moves the existing assignment before the comparisons. It runs after
`processIwlanRegistrationInfo()` and the other state preparation, because the
IWLAN/radio-off path can reset the new state again. It also precedes the
satellite-display checks and diagnostic state logging. The previous late
assignment is removed.

The patch does not change the aggregation getter, the per-SIM preference, or
carrier-family configuration. It does not change modem commands or attempt to
repair the separate cause-10 registration events. The original upstream
[Force LTE_CA commit](https://github.com/Evolution-X/frameworks_base/commit/53f69f74207ccf9d3c0029903190616964b693d4)
explicitly documents a reporting policy: ON reports LTE+ regardless of hardware
aggregation, while OFF/unset reports LTE even when hardware aggregation exists.
The getter calculates `hardwareCA` but intentionally does not use it as the
default result. Treating that default alone as a second confirmed bug was too
broad; restoring automatic hardware reporting would be a separate policy change.
Neither the existing preference nor such a change enables aggregation in the
modem or repairs a network detach. That behavior change is not included.

Three Android regression tests cover enabled, disabled, and unset preferences.
Each checks that an unchanged LTE poll does not notify service-state listeners
and that a real cell change still does. The tests restore the original setting
and unregister the listener. They use the existing simulated radio and
`ServiceStateTrackerTest` infrastructure.

The complete patched production class compiles with JDK 21 against 94
snapshotted dependencies and copied Android system modules from the current
ROM build. Compilation writes only to an isolated directory. The Android
regression tests are included for `FrameworksTelephonyTests` but have not been
executed on a device/test runtime. The compile check does not replace a full
ROM build or installed-phone validation.

Exact patch application, the patch driver's repeated-application skip, reverse
checking, and repository preflight are checked on isolated copies. The live
ROM source, build outputs, phone settings, and running build are not modified.
The fix takes effect after a ROM built with this patch is installed.
