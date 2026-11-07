Four patches address failures captured on Onyx on November 7, 2026.
They take effect after building and installing a ROM that includes them.

1. **Notification blur during background inflation** — framework patch `0012`.

   `onFinishInflate()` can run on `NotifInflation`, while the blur setter
   requires the main thread. Initialize blur from `onAttachedToWindow()`;
   background resource reloads update blur immediately only when attached.
   Attachment uses the latest transparency/keyguard state. Asynchronous row
   inflation, blur support and the setter's thread assertion are retained.

   An Android regression test constructs the real notification background
   on a worker thread with the blur feature flag enabled. An isolated host
   harness also exercises the production lifecycle methods against a model
   that rejects blur calls off the main thread.

2. **QS per-network Wi-Fi usage and aggregate labels** — framework patch `0013`.

   SystemUI did not request the fine-location permission required by
   `NetworkStatsService` for templates containing Wi-Fi network keys. Add
   the paired coarse/fine permissions to its manifest. SystemUI is a
   persistent, platform-signed privileged app, so the existing default
   permission grant policy covers these declarations. No background-location
   permission or NetworkStats permission-check bypass is added.

   Before selecting a keyed template, check the permission/app-op through
   `PermissionChecker.checkSelfPermissionForPreflight()`. A denied check
   selects aggregate Wi-Fi directly. The actual template determines whether
   the result represents one network, including when the network key is
   unavailable. A failed keyed query can still fall back to all Wi-Fi, but
   that result uses the generic Wi-Fi label instead of the current SSID.
   Failed aggregate queries are not repeated. Daily, weekly and mobile
   queries remain supported.

3. **Legacy radio region property** — device patch `0022`.

   `libxiaomi_qcril.so` contains real `property_get` call sites for
   `ro.miui.customized.region`, including both DSD UI-info overloads of
   `xiaomi_qcril_update_four_point_fiveg_unsol()`. The observed calls use an
   empty-string default. The existing device rule for
   `ro.vendor.miui.build.region` does not label this different name.

   Declare `miui_customized_region_prop` as a system-restricted property in
   system_ext public policy, label the legacy key with an **exact string**
   context in system_ext private policy, and grant `rild` its four ordinary
   property-file read permissions. Vendor writes remain forbidden. The
   existing BoardConfig already includes both policy directories. All seven
   carried system_ext compatibility ignore lists include the new exported
   type. No property value, vendor binary or broad `default_prop` permission
   is changed.

   Static evidence came from ordinary ELF/disassembly tools applied to an
   isolated library copy (SHA-256
   `165f4776eba144670cc309b4ebb6002b86968efa21bf596dd27d6ba93be937c4`).
   It corroborates the named-property/AVC correlation; it does not establish
   a modem outage or attribute every earlier radio denial to this property.

4. **Notification-history string pooling** — framework patch `0014`.

   Fresh buffer entries update the notification list without populating its
   string pool. Rebuild that pool immediately before serialization, then
   reuse one sorted snapshot for the pool and every notification index.
   Stale strings are discarded and repeated strings are deduplicated.
   The wire format and the reader's support for older inline strings remain
   unchanged. The Android regression test inspects the serialized pool;
   additional Robolectric cases verify field/order round trips and old data.

Validation used isolated source copies, not a running ROM build or phone
reconfiguration. The actual loader applied all four patches, skipped all
four on a second run without changing files, and rejected a deliberately
conflicting blur hunk. The actual generator reproduced their complete
intended diffs. These patches require exact application rather than fuzzy
relocation; an unresolved source conflict stops the build.

| Behavior checks | Original source | Patched source |
| --- | --- | --- |
| Blur lifecycle/thread boundary model | 3 passed, 3 failed | 6 passed |
| Wi-Fi query/label/service boundary model | 4 passed, 5 failed | 9 passed |
| Real Android protobuf serialization under Robolectric | 2 passed, 2 failed | 4 passed |

The serialization harness uses an existing Android 15 Robolectric runtime.
It compiles the production helper under a distinct class name so the SDK's
older helper cannot shadow it, and ignores unrelated APK metadata from the
reused test dependencies. The two boundary models are not on-device UI or
Binder tests. The Android regression tests still need their normal Android
test targets; this validation does not claim a full ROM build or deployment.

The radio policy compiled against a retained, preprocessed ROM policy
snapshot, passed its full neverallow checks and the property-context parser,
and explicitly rejected an attempted vendor write. The compiled policy
contains the expected `rild` read permissions and no added `default_prop`
read. New-property compatibility entries were checked for every carried API.

To rerun the host behavior checks with your own isolated snapshot and existing
dependencies:

```sh
ONYX_LOG_FIX_ROM=/path/to/isolated/rom \
ONYX_KOTLINC=/path/to/kotlinc \
ONYX_ANDROID_TEST_JAR=/path/to/android-all.jar \
ONYX_ROBOLECTRIC_TEST_JAR=/path/to/standalone-robolectric-tests.jar \
python3 -B ci/tests/test_log_fix_behavior.py -v
```

The Ooredoo/Madme wake-lock observation is outside these patches. Android
stopped the job under its background restriction and the blocker cleared.
That observation does not establish a stuck kernel wake lock; any further
fix needs evidence from the app's job/network lifecycle.
