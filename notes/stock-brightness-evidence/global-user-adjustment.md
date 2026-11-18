# Global stock user brightness adjustment

Verified from Onyx HyperOS Global 3.0.303 and China 3.0.305 shipped framework
artifacts on 2026-11-14. This is static shipped-code evidence, not a measurement
on a phone running HyperOS. The module's reference is Global stock, selected by
the user.

`BrightnessMappingStrategy.PhysicalMappingStrategy.addUserDataPoint()` records
the unadjusted brightness at the ambient lux, saves the user's lux/brightness
point, and recomputes the curve. Its `insertControlPoint()` calls Xiaomi's
`BrightnessMappingStrategyImpl.smoothNewCurveV2()` rather than AOSP's generic
`smoothCurve()`.

Global stock falls back to `smoothNewCurve()`. Let `u` be the saved unadjusted
brightness and `p` the inserted preferred brightness. At existing curve knots:

* Above the inserted point, stock evaluates `b = b - (u - p)`, then keeps each
  knot at least as bright as its preceding knot.
* Below it, stock evaluates `b = b - (((u - p) * b) / u)`, then keeps each knot
  no brighter than its following knot. Algebraically this is proportional
  scaling, but the port retains stock's floating-point operation order.
* The inserted control point stays at the selected brightness. The adjusted
  knots are converted back to nits and interpolated with a monotone cubic spline.
  Physical brightness conversion, white balance, Reduce Bright Colors, and
  output limits remain in their existing positions.

With Reduce Bright Colors active, stock's separately fitted cubic conversion
splines are not exact inverses. The correction preserves that stock conversion
behavior rather than adding a new inverse-fitting algorithm.

This allows brightness to respond to changing light while retaining a preference
at its anchor. It does not guarantee a different visible brightness for every
sensor sample: hysteresis, sensor debounce, physical limits, and saturation still
apply. In particular, a maximum preference in dim light can saturate above its
anchor. A simple Manual/Auto toggle retains the learned point; it does not reset
the preference. Stock has separate timeout and screen-off reset policies.

The correction ports the Global curve-adjustment algorithm. It retains the ROM's
existing Android model lifecycle rather than adding Xiaomi's cloud-dependent
screen-off reset policy. An Onyx-only guard covers undefined gamma inference
when the logarithmic gamma rounds to one and max gamma is also one. Valid
curve-smoothing inputs retain stock's arithmetic, including its `MathUtils.min`
handling of a zero baseline.

The China implementation is different despite identical class code.
`BrightnessCurve.isEnable()` requires `ro.miui.build.region=cn` and the curve
algorithm resource. Global's shipped property is `global`, so that path cannot
run. China can use its five-region V2 algorithm. The relevant default interval
is `[0, 30, 300, 4500, 20000]` lux. Refactor, custom-mode, and individual-model
features default false and have no shipped overlay override in either audited
image. This audit does not reproduce dynamic Xiaomi cloud or AI personalization.

The earlier candidate under `learning-trial5` used a custom affine nits warp.
Its tests demonstrated its own behavior, not stock equivalence. It was never
installed and is retained as rejected research. Its source and tests are
preserved under `learning-trial5/rejected-custom-affine`.

Evidence:

* Original archive identities: [artifact-identities.json](artifact-identities.json).
* Retained original decompilations:
  `/home/loukious/Android/onyx-auto-brightness-audit-20261114/evidence/stock`.
* Focused re-verification:
  `/home/loukious/Android/onyx-stock-brightness-ksu-20261114/learning-trial5/stock-verification/china`.
  It contains the full raw smali comparison of fourteen classes, rehashed jars,
  region properties, resource identities, and exhaustive relevant-resource
  coverage of 115 Global and 97 China overlay APKs with zero decode failures.
