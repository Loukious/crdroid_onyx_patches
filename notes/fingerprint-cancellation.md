The Xiaomi legacy-to-AIDL fingerprint adapter sends a synthetic
`onError(CANCELED)` as soon as the legacy HAL's `cancel()` returns zero.
`Session::notify()` also forwards the HAL's cancellation event. This can
finish the same framework client twice, or finish it before the vendor has
actually stopped its operation.

Both Xiaomi legacy headers (`fingerprint/include/fingerprint.h` and
`fingerprint-v2.h`) and the platform legacy HAL header specify that zero means
the cancellation request was accepted, and that the HAL sends
`FINGERPRINT_ERROR_CANCELED`. The return value is not another completion event.
The entire pre-fix `Session.cpp` matches
[crDroid's pinned upstream file](https://github.com/crdroidandroid/android_hardware_xiaomi/blob/3bf83ab759e0b1a8c2c6bc54b137a2b0549ff77f/aidl/fingerprint/Session.cpp).
This adapter behavior was inherited, not introduced by the custom kernel or
Secure Spaces fingerprint routing.

Patch `hardware_xiaomi/0001-fix-fingerprint-cancel-completion.patch` removes
only the synthetic callback. It preserves the vendor notification path,
request error status, and UDFPS cleanup order. It adds no event suppression,
timeout, or framework authentication change.

The host regression runner compiles the actual `Session::cancel`,
`Session::VendorErrorFilter`, and complete `Session::notify` methods against
HAL/Binder models, using both normal and `IMPL_V2` branches with undefined
behavior sanitization. Seven cases check synchronous and asynchronous
cancellation, absent UDFPS handlers, request errors, real vendor errors,
terminal results racing cancellation, and independent subsequent operations.
The original source passes one case and fails six in each branch; the patched
source passes all seven in each branch.

```sh
python3 -B ci/check-fingerprint-cancel.py /isolated/Session.cpp --out /tmp/fingerprint-check
```

Exact patch application, repeated application, reverse checking, generation,
and repository preflight are validated on isolated copies. Host models do not
validate the complete Android service ABI or real fingerprint matching.
Deployment requires rebuilding and installing the fingerprint service/ROM.
The validation does not modify the live ROM source or deploy anything to the
phone.
