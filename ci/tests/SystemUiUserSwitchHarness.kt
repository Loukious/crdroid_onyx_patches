import android.view.View
import com.android.internal.graphics.drawable.BackgroundBlurDrawable
import com.android.internal.widget.LockPatternUtils.StrongAuthTracker.STRONG_AUTH_REQUIRED_AFTER_BOOT
import com.android.internal.widget.LockPatternUtils.StrongAuthTracker.STRONG_AUTH_REQUIRED_AFTER_LOCKOUT
import com.android.systemui.authentication.shared.model.AuthenticationMethodModel
import com.android.systemui.bouncer.shared.model.*
import com.android.systemui.common.ui.view.BackgroundBlurAlphaSync
import com.android.systemui.keyguard.shared.model.AuthenticationFlags
import com.android.systemui.res.R
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*

enum class SecurityMode {
    Invalid, None, Pattern, Password, PIN, SimPin, SimPuk, SecureLockDeviceBiometricAuth
}
data class UserInfo(val id: Int)
class Users { val selectedUserInfo = MutableStateFlow(UserInfo(0)) }
class Bouncer { val lastShownSecurityMode = MutableStateFlow(SecurityMode.PIN) }
class Trust {
    val isCurrentUserTrustManaged = MutableStateFlow(false)
    val isCurrentUserTrustUsuallyManaged = MutableStateFlow(false)
}
class Biometrics {
    val isFingerprintLockedOut = MutableStateFlow(false)
    val isFaceLockedOut = MutableStateFlow(false)
}
class Settings {
    val isFingerprintEnrolledAndEnabled = MutableStateFlow(true)
    val isFaceAuthEnrolledAndEnabled = MutableStateFlow(false)
}
data class Modalities(val hasFingerprint: Boolean = true, val hasFace: Boolean = false)
class SecureLock { val enrolledStrongBiometricModalities = MutableStateFlow(Modalities()) }
class LazySecure { private val value = SecureLock(); fun get() = value }
data class Nonuple<A, B, C, D, E, F, G, H, I>(
    val a: A, val b: B, val c: C, val d: D, val e: E,
    val f: F, val g: G, val h: H, val i: I,
)
@Suppress("UNCHECKED_CAST")
fun <A, B, C, D, E, F, G, H, I, T> combine(
    a: Flow<A>, b: Flow<B>, c: Flow<C>, d: Flow<D>, e: Flow<E>,
    f: Flow<F>, g: Flow<G>, h: Flow<H>, i: Flow<I>,
    transform: (A, B, C, D, E, F, G, H, I) -> T,
): Flow<T> = combine(a, b, c, d, e, f, g, h, i) { values: Array<Any?> ->
    transform(values[0] as A, values[1] as B, values[2] as C, values[3] as D,
        values[4] as E, values[5] as F, values[6] as G, values[7] as H, values[8] as I)
}

class Messages {
    val userRepository = Users()
    val primaryBouncerInteractor = Bouncer()
    val trustRepository = Trust()
    val authenticationFlags = MutableStateFlow(AuthenticationFlags(0, 0))
    val biometricSettingsRepository = Settings()
    val deviceEntryBiometricsAllowedInteractor = Biometrics()
    val isAnyBiometricsEnabledAndEnrolled = MutableStateFlow(true)
    val isFingerprintAuthCurrentlyAllowedOnBouncer = MutableStateFlow(false)
    val isFaceAuthCurrentlyAllowedOnBouncer = MutableStateFlow(false)
    val secureLockDeviceInteractor = LazySecure()
    var wasRebootedForMainlineUpdate = false
    var isFaceAuthClass3 = false
    fun isSecureLockDeviceEnabled() = false
    val currentUserId get() = userRepository.selectedUserInfo.value.id
    val currentSecurityMode get() = primaryBouncerInteractor.lastShownSecurityMode.value
    val defaultMessage get() = BouncerMessageStrings.defaultMessage(
        currentSecurityMode.toAuthModel(), isFingerprintAuthCurrentlyAllowedOnBouncer.value,
        isFaceAuthCurrentlyAllowedOnBouncer.value).toMessage()

    // PRODUCTION_MESSAGE_FLOW
    fun messages() = initialBouncerMessage
}

// PRODUCTION_MESSAGE_HELPERS

var passed = 0
var failed = 0
fun case(name: String, block: () -> Unit) {
    try { block(); passed++ } catch (e: Throwable) {
        failed++; println("FAIL $name: $e")
    }
}
fun eq(actual: Any?, expected: Any?) {
    check(actual == expected) { "$actual != $expected" }
}

fun main() = runBlocking {
    for ((name, values, expected) in listOf(
        Triple("before layout", intArrayOf(0, 0, 0), 0f),
        Triple("equal heights", intArrayOf(300, 300, 300), 0f),
        Triple("reversed heights", intArrayOf(300, 100, 200), 0f),
        Triple("below minimum", intArrayOf(300, 1000, 200), 0f),
        Triple("collapsed", intArrayOf(300, 1000, 300), 0f),
        Triple("half expanded", intArrayOf(300, 1000, 650), 0.5f),
        Triple("fully expanded", intArrayOf(300, 1000, 1000), 1f),
        Triple("above maximum", intArrayOf(300, 1000, 1200), 1f),
    )) case("QS $name") {
        val qs = Qs()
        qs.mMinExpansionHeight = values[0]; qs.mMaxExpansionHeight = values[1]
        qs.mExpansionHeight = values[2].toFloat()
        eq(qs.computeExpansionFraction(), expected)
    }
    case("QS layout recovery") {
        val qs = Qs(); eq(qs.computeExpansionFraction(), 0f)
        qs.mMaxExpansionHeight = 1000; qs.mExpansionHeight = 500f
        eq(qs.computeExpansionFraction(), 0.5f)
        qs.mAnimatingHiddenFromCollapsed = true; eq(qs.computeExpansionFraction(), 0f)
    }
    case("blur hierarchy multiplication") {
        val v = View(); v.alpha = 0.5f
        v.parent = View().apply { alpha = 0.5f; transitionAlpha = 0.5f }
        val drawable = BackgroundBlurDrawable()
        BackgroundBlurAlphaSync(v) { drawable }.sync(); eq(drawable.alpha, 32)
    }
    for ((name, invalid) in listOf("NaN" to Float.NaN, "+inf" to Float.POSITIVE_INFINITY,
                                   "-inf" to Float.NEGATIVE_INFINITY)) {
        case("blur $name ancestor and recovery") {
            val parent = View().apply { alpha = invalid }
            val v = View().apply { this.parent = parent }
            val drawable = BackgroundBlurDrawable()
            val sync = BackgroundBlurAlphaSync(v) { drawable }
            sync.sync(); eq(drawable.alpha, 0)
            parent.alpha = 0.5f; sync.sync(); eq(drawable.alpha, 128)
        }
    }
    case("blur invalid transition alpha") {
        val v = View().apply { transitionAlpha = Float.NaN }
        val drawable = BackgroundBlurDrawable()
        check(BackgroundBlurAlphaSync(v) { drawable }.onPreDraw()); eq(drawable.alpha, 0)
    }
    case("blur null drawable") { BackgroundBlurAlphaSync(View()) { null }.sync() }
    case("QS zero range to lock icon blur") {
        val qsProgress = Qs().computeExpansionFraction()
        // DeviceEntryIconViewModel's shade alpha multiplier, with shade closed.
        val interpolatedQsProgress = (qsProgress * 2).coerceIn(0f, 1f)
        val v = View().apply { alpha = (1f - 0f) * (1f - interpolatedQsProgress) }
        val drawable = BackgroundBlurDrawable()
        BackgroundBlurAlphaSync(v) { drawable }.sync(); eq(drawable.alpha, 255)
    }
    for (mode in listOf(SecurityMode.PIN, SecurityMode.Pattern, SecurityMode.Password)) {
        val m = Messages()
        m.primaryBouncerInteractor.lastShownSecurityMode.value = mode
        var observed: BouncerMessageModel? = null
        val job = launch { m.messages().collect { observed = it } }
        suspend fun settle() { repeat(50) { yield() } }
        fun secondary() = observed?.secondaryMessage?.messageResId
        val reboot = BouncerMessageStrings.authRequiredAfterReboot(mode.toAuthModel()).second
        val lockout = BouncerMessageStrings.class3AuthLockedOut(mode.toAuthModel()).second
        settle()
        case("$mode initial neutral") { eq(secondary(), 0) }
        m.authenticationFlags.value = AuthenticationFlags(0, STRONG_AUTH_REQUIRED_AFTER_BOOT)
        settle()
        case("$mode real reboot") { eq(secondary(), reboot) }
        m.userRepository.selectedUserInfo.value = UserInfo(11)
        settle()
        case("$mode selection before flags") { eq(secondary(), 0) }
        m.authenticationFlags.value = AuthenticationFlags(11, STRONG_AUTH_REQUIRED_AFTER_LOCKOUT)
        settle()
        case("$mode lockout without sensor lockout") { eq(secondary(), lockout) }
        m.authenticationFlags.value = AuthenticationFlags(11, 0)
        settle()
        case("$mode cleared lockout") { eq(secondary(), 0) }
        m.authenticationFlags.value = AuthenticationFlags(0, STRONG_AUTH_REQUIRED_AFTER_BOOT)
        settle()
        case("$mode flags before selection") { eq(secondary(), 0) }
        m.userRepository.selectedUserInfo.value = UserInfo(0)
        settle()
        case("$mode matching reboot flags") { eq(secondary(), reboot) }
        m.authenticationFlags.value = AuthenticationFlags(0,
            STRONG_AUTH_REQUIRED_AFTER_BOOT or STRONG_AUTH_REQUIRED_AFTER_LOCKOUT)
        settle()
        case("$mode reboot retains priority") { eq(secondary(), reboot) }
        job.cancelAndJoin()
    }
    println("passed=$passed failed=$failed")
    check(failed == 0)
}
