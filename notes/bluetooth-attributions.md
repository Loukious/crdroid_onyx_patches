Bluetooth's internal GATT clients set attribution tags that its manifest does
not declare. The November 7 Onyx log capture contains 51 instances of
`attributionTag BatteryService not declared in manifest of com.android.bluetooth`.
The installed Bluetooth APK's decoded manifest has no attribution declarations.

`BatteryStateMachine.connectGatt()` assigns `BatteryService` through
`AttributionSource.Builder.setAttributionTag()`. The equivalent path in
`BassClientStateMachine` assigns `BassClient`; this second omission is confirmed
in source, although that tag did not produce a recorded error in the capture.
The current synced source still lacks both declarations.

Patch `packages_modules_Bluetooth/0002-declare-profile-attributions.patch`
adds two manifest-level attribution elements and their labels in
`android/app/res/values/attributions.xml`. AppOps can then retain the tags when
recording access. Its existing behavior for an undeclared tag is to log an
error and fall back to untagged accounting. The observed defect concerns
attribution; it does not establish failed Bluetooth connections or missing
accessory battery readings.

The patch changes only metadata. Permission declarations, application flags,
GATT behavior and AppOps validation remain unchanged. The generator excludes
these two files from the LHDC patch and emits them as the separate attribution
patch. The existing LHDC patch does not touch either file.

Validation uses isolated source copies. It checks the full modified manifest,
matches the declarations to both existing call sites, and resolves each label.
AAPT2 compiles the new resource file and links the actual attribution elements
in a minimal manifest against the Android SDK, then decodes the result to
verify both tags survived resource linking. This is a focused resource check,
not a complete Bluetooth APEX or ROM build.

Patch application, repeated application, reverse checking, regeneration and
the repository preflight are also checked. Deployment requires a Bluetooth
module/ROM built with this patch. No phone service restart or change to a
running ROM build is part of this validation.
