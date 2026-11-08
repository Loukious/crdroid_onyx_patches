"""Host dependencies for the unchanged FromLockscreenTransitionInteractor.

Coroutines and StateFlow are real. Android services, traversal, and transition
storage are small models; this does not exercise Android rendering or input.
"""

SOURCES = {
    "android/animation/ValueAnimator.kt": """
package android.animation
class ValueAnimator { var interpolator: Any? = null; var duration: Long = 0 }
""",
    "android/util/Utils.kt": """
package android.util
object Log { fun i(tag: String, message: String) = 0 }
object MathUtils {
    fun constrainedMap(outMin: Float, outMax: Float, min: Float, max: Float, value: Float): Float =
        outMin + (outMax - outMin) * ((value - min) / (max - min)).coerceIn(0f, 1f)
}
""",
    "com/android/app/animation/Interpolators.kt": """
package com.android.app.animation
object Interpolators { val LINEAR = Any() }
""",
    "com/android/app/tracing/coroutines/Launch.kt": """
package com.android.app.tracing.coroutines
import kotlinx.coroutines.*
fun CoroutineScope.launchTraced(name: String = "", block: suspend CoroutineScope.() -> Unit): Job =
    launch(block = block)
""",
    "javax/inject/Inject.kt": """
package javax.inject
annotation class Inject
""",
    "com/android/systemui/dagger/Annotations.kt": """
package com.android.systemui.dagger
annotation class SysUISingleton
""",
    "com/android/systemui/dagger/qualifiers/Annotations.kt": """
package com.android.systemui.dagger.qualifiers
annotation class Application
annotation class Background
annotation class Main
""",
    "com/android/systemui/bouncer/shared/constants/Constants.kt": """
package com.android.systemui.bouncer.shared.constants
object KeyguardBouncerConstants {
    const val EXPANSION_VISIBLE = 0f
    const val EXPANSION_HIDDEN = 1f
}
""",
    "com/android/systemui/bouncer/domain/interactor/PrimaryBouncerInteractor.kt": """
package com.android.systemui.bouncer.domain.interactor
import kotlinx.coroutines.flow.MutableStateFlow
import host.QueueDispatcher
class PrimaryBouncerInteractor(private val main: QueueDispatcher) {
    val isShowing = MutableStateFlow(false)
    val isShowingSoon = MutableStateFlow(false)
    var expansion = 1f
    var scrimmed = false
    var showCalls = 0
    val expansions = mutableListOf<Float>()
    fun show(isScrimmed: Boolean, reason: String): Boolean {
        main.assertCurrent()
        showCalls++
        scrimmed = isScrimmed
        isShowingSoon.value = true
        return true
    }
    fun setPanelExpansion(value: Float) {
        main.assertCurrent()
        val previous = expansion
        expansion = value
        expansions += value
        if (value == 1f && previous != 1f) hide()
    }
    fun hide() {
        isShowing.value = false
        isShowingSoon.value = false
        expansion = 1f
    }
    fun finishTraversal() {
        if (isShowingSoon.value) {
            isShowing.value = true
            isShowingSoon.value = false
        }
    }
}
""",
    "com/android/systemui/communal/shared/model/CommunalScenes.kt": """
package com.android.systemui.communal.shared.model
object CommunalScenes { val Communal = Any() }
""",
    "com/android/systemui/communal/domain/interactor/Interactors.kt": """
package com.android.systemui.communal.domain.interactor
import kotlinx.coroutines.flow.MutableStateFlow
class CommunalSceneInteractor { fun changeScene(newScene: Any, loggingReason: String) {} }
class CommunalSettingsInteractor {
    val autoOpenEnabled = MutableStateFlow(false)
    fun isV2FlagEnabled() = false
}
""",
    "com/android/systemui/power/shared/model/WakeSleepReason.kt": """
package com.android.systemui.power.shared.model
enum class WakeSleepReason { FOLD, OTHER }
""",
    "com/android/systemui/power/domain/interactor/PowerInteractor.kt": """
package com.android.systemui.power.domain.interactor
import com.android.systemui.power.shared.model.WakeSleepReason
import kotlinx.coroutines.flow.MutableStateFlow
data class Wakefulness(val lastSleepReason: WakeSleepReason = WakeSleepReason.OTHER)
class PowerInteractor { val detailedWakefulness = MutableStateFlow(Wakefulness()) }
""",
    "com/android/systemui/scene/shared/flag/SceneContainerFlag.kt": """
package com.android.systemui.scene.shared.flag
object SceneContainerFlag { var isEnabled = false }
""",
    "com/android/systemui/scene/shared/model/Scenes.kt": """
package com.android.systemui.scene.shared.model
object Scenes { val Gone = Any() }
""",
    "com/android/systemui/shade/data/repository/ShadeRepository.kt": """
package com.android.systemui.shade.data.repository
import kotlinx.coroutines.flow.MutableStateFlow
class ShadeRepository {
    val legacyShadeExpansion = MutableStateFlow(1f)
    val legacyShadeTracking = MutableStateFlow(false)
}
""",
    "com/android/systemui/keyguard/shared/model/Models.kt": """
package com.android.systemui.keyguard.shared.model
import android.animation.ValueAnimator
enum class KeyguardState { OFF, LOCKSCREEN, PRIMARY_BOUNCER, ALTERNATE_BOUNCER,
    OCCLUDED, AOD, DOZING, DREAMING, GONE, GLANCEABLE_HUB }
object StatusBarState { const val KEYGUARD = 1 }
enum class TransitionState { STARTED, RUNNING, FINISHED, CANCELED }
enum class TransitionModeOnCanceled { REVERSE, RESET, LAST_VALUE }
data class TransitionInfo(
    val ownerName: String,
    val from: KeyguardState,
    val to: KeyguardState,
    val animator: ValueAnimator?,
    val modeOnCanceled: TransitionModeOnCanceled = TransitionModeOnCanceled.LAST_VALUE,
)
data class TransitionStep(
    val from: KeyguardState = KeyguardState.OFF,
    val to: KeyguardState = KeyguardState.LOCKSCREEN,
    val value: Float = 1f,
    val transitionState: TransitionState = TransitionState.FINISHED,
    val ownerName: String = "",
)
class Edge { companion object { fun create(from: KeyguardState, to: Any) = Edge() } }
""",
    "com/android/systemui/keyguard/data/repository/KeyguardTransitionRepository.kt": """
package com.android.systemui.keyguard.data.repository
import com.android.systemui.keyguard.shared.model.*
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.MutableStateFlow
import java.util.UUID
class KeyguardTransitionRepository {
    var currentTransitionInfo = TransitionInfo("initial", KeyguardState.OFF,
        KeyguardState.LOCKSCREEN, null)
    val transitionState = MutableStateFlow(TransitionStep())
    val started = MutableStateFlow(TransitionStep())
    val finished = MutableStateFlow(KeyguardState.LOCKSCREEN)
    var holdStart: CompletableDeferred<Unit>? = null
    val requests = mutableListOf<TransitionInfo>()
    var activeId: UUID? = null
    fun emit(step: TransitionStep) {
        if (step.transitionState == TransitionState.STARTED) started.value = step
        if (step.transitionState == TransitionState.FINISHED) finished.value = step.to
        transitionState.value = step
    }
    suspend fun startTransition(info: TransitionInfo): UUID? {
        currentTransitionInfo = info
        requests += info
        activeId = if (info.animator == null) UUID.randomUUID() else null
        val id = activeId
        emit(TransitionStep(info.from, info.to, 0f, TransitionState.STARTED, info.ownerName))
        holdStart?.await()
        return id
    }
    suspend fun updateTransition(id: UUID, value: Float, state: TransitionState) {
        if (id != activeId) return
        emit(transitionState.value.copy(value = value, transitionState = state))
        if (state == TransitionState.CANCELED || state == TransitionState.FINISHED) activeId = null
    }
}
""",
    "com/android/systemui/keyguard/domain/interactor/Interactors.kt": """
package com.android.systemui.keyguard.domain.interactor
import android.animation.ValueAnimator
import com.android.systemui.keyguard.data.repository.KeyguardTransitionRepository
import com.android.systemui.keyguard.shared.model.*
import com.android.systemui.power.domain.interactor.PowerInteractor
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import java.util.UUID
class InternalKeyguardTransitionInteractor(private val repository: KeyguardTransitionRepository) {
    fun currentTransitionInfoInternal() = repository.currentTransitionInfo
}
class KeyguardTransitionInteractor(repository: KeyguardTransitionRepository) {
    val transitionState = repository.transitionState
    val startedKeyguardTransitionStep = repository.started
    val finishedKeyguardState = repository.finished
    fun transition(edge: Edge, edgeWithoutSceneContainer: Edge): Flow<TransitionStep> = emptyFlow()
}
class KeyguardInteractor {
    val isDreamingNotDozing = MutableStateFlow(false)
    val primaryBouncerShowing = MutableStateFlow(false)
    val alternateBouncerShowing = MutableStateFlow(false)
    val statusBarState = MutableStateFlow(StatusBarState.KEYGUARD)
    val isKeyguardDismissible = MutableStateFlow(false)
    val isKeyguardOccluded = MutableStateFlow(false)
    val isKeyguardGoingAway = MutableStateFlow(false)
    val asleepKeyguardState = MutableStateFlow(KeyguardState.DOZING)
}
class KeyguardOcclusionInteractor
class SwipeToDismissInteractor
abstract class TransitionInteractor(
    val fromState: KeyguardState,
    val transitionInteractor: KeyguardTransitionInteractor,
    val mainDispatcher: CoroutineDispatcher,
    val bgDispatcher: CoroutineDispatcher,
    val powerInteractor: PowerInteractor,
    val keyguardOcclusionInteractor: KeyguardOcclusionInteractor,
    val keyguardInteractor: KeyguardInteractor,
) {
    val name = "FromLockscreenTransitionInteractor"
    abstract val transitionRepository: KeyguardTransitionRepository
    abstract val internalTransitionInteractor: InternalKeyguardTransitionInteractor
    abstract fun start()
    abstract fun getDefaultAnimatorForTransitionsToState(toState: KeyguardState): ValueAnimator
    suspend fun startTransitionTo(toState: KeyguardState,
        animator: ValueAnimator? = getDefaultAnimatorForTransitionsToState(toState),
        modeOnCanceled: TransitionModeOnCanceled = TransitionModeOnCanceled.LAST_VALUE,
        ownerReason: String = ""): UUID? {
        if (internalTransitionInteractor.currentTransitionInfoInternal().to != fromState) return null
        return transitionRepository.startTransition(TransitionInfo(name + ownerReason,
            fromState, toState, animator, modeOnCanceled))
    }
    fun <T> Flow<T>.filterRelevantKeyguardState(): Flow<T> =
        filter { internalTransitionInteractor.currentTransitionInfoInternal().to == fromState }
    fun <T> Flow<T>.filterRelevantKeyguardStateAnd(predicate: (T) -> Boolean): Flow<T> =
        filterRelevantKeyguardState().filter(predicate)
    fun listenForTransitionToCamera(scope: CoroutineScope, interactor: KeyguardInteractor) {}
    suspend fun listenForSleepTransition(
        modeOnCanceledFromStartedStep: (TransitionStep) -> TransitionModeOnCanceled) {}
}
""",
    "host/QueueDispatcher.kt": """
package host
import kotlin.coroutines.CoroutineContext
import kotlinx.coroutines.CoroutineDispatcher
class QueueDispatcher(private val label: String): CoroutineDispatcher() {
    private val queue = ArrayDeque<Runnable>()
    companion object { private var running: QueueDispatcher? = null }
    override fun dispatch(context: CoroutineContext, block: Runnable) { queue.addLast(block) }
    fun assertCurrent() { check(running === this) { "bouncer mutated outside $label" } }
    fun runCurrent(): Boolean {
        var count = 0
        while (queue.isNotEmpty()) {
            check(count++ < 1000) { "dispatcher loop: $label" }
            val previous = running
            running = this
            try { queue.removeFirst().run() } finally { running = previous }
        }
        return count != 0
    }
}
""",
}
