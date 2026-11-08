import android.animation.ValueAnimator
import com.android.systemui.bouncer.domain.interactor.PrimaryBouncerInteractor
import com.android.systemui.communal.domain.interactor.CommunalSceneInteractor
import com.android.systemui.communal.domain.interactor.CommunalSettingsInteractor
import com.android.systemui.keyguard.data.repository.KeyguardTransitionRepository
import com.android.systemui.keyguard.domain.interactor.*
import com.android.systemui.keyguard.shared.model.*
import com.android.systemui.keyguard.shared.model.KeyguardState.*
import com.android.systemui.keyguard.shared.model.TransitionState.*
import com.android.systemui.power.domain.interactor.PowerInteractor
import com.android.systemui.scene.shared.flag.SceneContainerFlag
import com.android.systemui.shade.data.repository.ShadeRepository
import host.QueueDispatcher
import kotlinx.coroutines.*

private class Fixture(sceneContainer: Boolean = false) : AutoCloseable {
    val main = QueueDispatcher("main")
    val background = QueueDispatcher("background")
    private val mainJob = SupervisorJob()
    private val backgroundJob = SupervisorJob()
    private val applicationScope = CoroutineScope(mainJob + main)
    private val backgroundScope = CoroutineScope(backgroundJob + background)
    val repository = KeyguardTransitionRepository()
    val shade = ShadeRepository()
    val bouncer = PrimaryBouncerInteractor(main)
    private val subject = FromLockscreenTransitionInteractor(
        repository, InternalKeyguardTransitionInteractor(repository),
        KeyguardTransitionInteractor(repository), backgroundScope, applicationScope,
        background, main, KeyguardInteractor(), shade, PowerInteractor(),
        CommunalSettingsInteractor(), CommunalSceneInteractor(), SwipeToDismissInteractor(),
        KeyguardOcclusionInteractor(), bouncer,
    )

    init {
        SceneContainerFlag.isEnabled = sceneContainer
        subject.start()
        drain()
    }

    fun drain() {
        repeat(30) {
            val ui = main.runCurrent()
            val bg = background.runCurrent()
            if (!ui && !bg) return
        }
        error("coroutine queues did not become idle")
    }

    fun queueRepair(expansion: Float, animated: Boolean = false) {
        shade.legacyShadeExpansion.value = expansion
        repository.currentTransitionInfo = TransitionInfo(
            "test", LOCKSCREEN, PRIMARY_BOUNCER, if (animated) ValueAnimator() else null,
        )
        repository.emit(TransitionStep(LOCKSCREEN, PRIMARY_BOUNCER, 0.3f, RUNNING))
        // Let the background collector accept the event and suspend in withContext(main).
        background.runCurrent()
    }

    fun transitionAway(to: KeyguardState) {
        bouncer.hide()
        repository.currentTransitionInfo = TransitionInfo("replacement", PRIMARY_BOUNCER, to,
            ValueAnimator())
        repository.emit(TransitionStep(PRIMARY_BOUNCER, to, 0f, STARTED))
    }

    fun assertHidden() {
        bouncer.finishTraversal()
        check(!bouncer.isShowing.value && !bouncer.isShowingSoon.value) {
            "cancelled bouncer reopened (shows=${bouncer.showCalls}, expansion=${bouncer.expansion})"
        }
        check(bouncer.expansion == 1f) { "hidden bouncer expansion=${bouncer.expansion}" }
    }

    override fun close() {
        mainJob.cancel()
        backgroundJob.cancel()
        drain()
        SceneContainerFlag.isEnabled = false
    }
}

fun main() {
    var passed = 0
    var failed = 0
    fun test(name: String, block: () -> Unit) {
        try {
            block()
            passed++
            println("PASS $name")
        } catch (failure: Throwable) {
            failed++
            println("FAIL $name: ${failure.message}")
        }
    }

    test("half swipe keeps its actual expansion") {
        Fixture().use { f ->
            f.queueRepair(0.6f)
            f.drain()
            check(f.bouncer.expansion == 0.6f) { "expansion=${f.bouncer.expansion}" }
        }
    }
    test("queued repair samples the latest swipe position on main") {
        Fixture().use { f ->
            f.queueRepair(0.4f)
            f.shade.legacyShadeExpansion.value = 0.9f
            f.drain()
            check(f.bouncer.expansion == 0.9f) { "expansion=${f.bouncer.expansion}" }
        }
    }
    test("cancellation at the hidden endpoint never queues a show") {
        Fixture().use { f ->
            f.queueRepair(1f)
            f.drain()
            f.assertHidden()
            check(f.bouncer.showCalls == 0)
        }
    }
    for (destination in listOf(LOCKSCREEN, GONE, DOZING, OCCLUDED)) {
        test("late callback cannot reopen bouncer after transition to $destination") {
            Fixture().use { f ->
                f.queueRepair(0.5f)
                f.transitionAway(destination)
                f.drain()
                f.assertHidden()
                check(f.bouncer.showCalls == 0)
            }
        }
    }
    test("animated bouncer keeps its expansion and scrim owner") {
        Fixture().use { f ->
            f.bouncer.isShowingSoon.value = true
            f.bouncer.scrimmed = true
            f.bouncer.expansion = 0f
            f.queueRepair(1f, animated = true)
            f.drain()
            check(f.bouncer.scrimmed) { "scrim ownership overwritten" }
            check(f.bouncer.showCalls == 0 && f.bouncer.expansions.isEmpty())
        }
    }
    test("manual bridge still repairs invisible bouncer after biometric dismissal") {
        Fixture().use { f ->
            f.bouncer.isShowingSoon.value = true
            f.queueRepair(0f)
            f.drain()
            f.bouncer.finishTraversal()
            check(f.bouncer.showCalls == 1 && f.bouncer.isShowing.value)
            check(f.bouncer.expansion == 0f)
        }
    }
    test("normal swipe reaches fully shown state") {
        Fixture().use { f ->
            f.shade.legacyShadeTracking.value = true
            f.shade.legacyShadeExpansion.value = 0.6f
            f.drain()
            f.bouncer.finishTraversal()
            f.shade.legacyShadeTracking.value = false
            f.shade.legacyShadeExpansion.value = 0f
            f.drain()
            check(f.bouncer.isShowing.value && f.bouncer.expansion == 0f)
            check(f.repository.transitionState.value.transitionState == FINISHED)
        }
    }
    test("cancelled swipe can be followed by a fresh successful swipe") {
        Fixture().use { f ->
            f.shade.legacyShadeTracking.value = true
            f.shade.legacyShadeExpansion.value = 0.6f
            f.drain()
            f.bouncer.finishTraversal()
            f.queueRepair(0.7f)
            f.shade.legacyShadeTracking.value = false
            f.shade.legacyShadeExpansion.value = 1f
            f.drain()
            f.assertHidden()
            check(f.repository.currentTransitionInfo.to == LOCKSCREEN)
            f.shade.legacyShadeTracking.value = true
            f.shade.legacyShadeExpansion.value = 0.5f
            f.drain()
            f.bouncer.finishTraversal()
            f.shade.legacyShadeExpansion.value = 0f
            f.drain()
            check(f.bouncer.isShowing.value && f.bouncer.expansion == 0f)
        }
    }
    test("suspended manual start cannot resurrect a cancelled swipe") {
        Fixture().use { f ->
            val gate = CompletableDeferred<Unit>()
            f.repository.holdStart = gate
            f.shade.legacyShadeTracking.value = true
            f.shade.legacyShadeExpansion.value = 0.5f
            f.main.runCurrent()
            f.background.runCurrent()
            f.shade.legacyShadeTracking.value = false
            f.shade.legacyShadeExpansion.value = 1f
            f.transitionAway(LOCKSCREEN)
            gate.complete(Unit)
            f.drain()
            f.assertHidden()
            check(f.bouncer.showCalls == 0)
        }
    }
    test("scene container does not run the legacy bouncer bridge") {
        Fixture(sceneContainer = true).use { f ->
            f.queueRepair(0.5f)
            f.drain()
            check(f.bouncer.showCalls == 0 && f.bouncer.expansions.isEmpty())
        }
    }
    println("passed=$passed failed=$failed")
    check(failed == 0) { "$failed regression tests failed" }
}
