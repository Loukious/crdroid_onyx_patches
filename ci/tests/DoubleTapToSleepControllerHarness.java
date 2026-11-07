// Runs the complete production controller with the host boundaries in dt2s_host_models.py.
// These are controller lifecycle tests, not Android GestureDetector or native input tests.
import android.app.ActivityTaskManager;
import android.app.TaskInfo;
import android.app.WindowConfiguration;
import android.content.ComponentName;
import android.content.Context;
import android.os.Handler;
import android.os.PowerManager;
import android.os.SystemClock;
import android.view.MotionEvent;
import android.window.WindowInfosListenerForTest;
import android.window.WindowInfosListenerForTest.WindowInfo;
import com.android.systemui.LauncherProxyService;
import com.android.systemui.dt2s.DoubleTapToSleepController;
import com.android.systemui.keyguard.KeyguardUnlockAnimationController;
import com.android.systemui.keyguard.data.repository.InWindowLauncherUnlockAnimationRepository;
import com.android.systemui.plugins.FalsingManager;
import com.android.systemui.shade.domain.interactor.ShadeInteractor;
import com.android.systemui.shared.system.InputMonitorCompat;
import com.android.systemui.shared.system.TaskStackChangeListeners;
import com.android.systemui.statusbar.CommandQueue;
import com.android.systemui.tuner.TunerService;
import com.android.systemui.util.kotlin.JavaAdapter;
import com.android.wm.shell.shared.ShellTransitions;
import dagger.Lazy;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Executor;
import kotlinx.coroutines.flow.StateFlow;

public class DoubleTapToSleepControllerHarness {
    private static final String LAUNCHER = "com.google.android.apps.nexuslauncher";

    private static void check(boolean condition, String reason) {
        if (!condition) throw new AssertionError(reason);
    }

    private static final class Fixture {
        final Handler main = new Handler();
        final PowerManager power = new PowerManager();
        final FalsingManager falsing = new FalsingManager();
        final CommandQueue commands = new CommandQueue();
        final TunerService tuner = new TunerService();
        final LauncherProxyService launcher = new LauncherProxyService();
        final StateFlow<Boolean> expanded;
        final DoubleTapToSleepController controller;

        Fixture() throws Exception { this(false, false); }

        Fixture(boolean shadeOpen, boolean holdDelivery) throws Exception {
            SystemClock.now = 1000;
            InputMonitorCompat.reset();
            WindowInfosListenerForTest.listeners = 0;
            WindowInfosListenerForTest.windows = List.of(
                    new WindowInfo("NotificationShade", true), new WindowInfo(LAUNCHER, false));
            TaskInfo home = new TaskInfo();
            home.topActivity = new ComponentName(LAUNCHER);
            home.activityType = WindowConfiguration.ACTIVITY_TYPE_HOME;
            ActivityTaskManager.focused = home;
            expanded = new StateFlow<>(shadeOpen);
            expanded.holdDelivery = holdDelivery;
            List<Object> args = new ArrayList<>(List.of(
                    new Context(), power, falsing, commands, main,
                    (Executor) Runnable::run, tuner, new ShellTransitions(), launcher,
                    (Lazy<KeyguardUnlockAnimationController>) KeyguardUnlockAnimationController::new,
                    (Lazy<InWindowLauncherUnlockAnimationRepository>) InWindowLauncherUnlockAnimationRepository::new));
            // Instantiate either the original or patched production constructor, without editing it.
            var constructor = DoubleTapToSleepController.class.getConstructors()[0];
            if (constructor.getParameterCount() == args.size() + 2) {
                args.add(new ShadeInteractor(expanded));
                args.add(new JavaAdapter(main));
            }
            controller = (DoubleTapToSleepController) constructor.newInstance(args.toArray());
            controller.start();
            main.drain();
        }

        void shade(boolean open) { expanded.setValue(open); main.drain(); }

        void tap() { tap(500, 800, 1); }

        void tap(float x, float y, int pointers) {
            InputMonitorCompat.dispatch(new MotionEvent(MotionEvent.ACTION_DOWN, pointers, x, y));
            InputMonitorCompat.dispatch(new MotionEvent(MotionEvent.ACTION_UP, pointers, x, y));
        }

        void doubleTap() { tap(); main.advanceBy(80); tap(); }

        void finishSleepDelay() { main.advanceBy(350); }

        void awake() { check(power.sleeps == 0, "unexpected goToSleep call"); }

        void monitoring(boolean expected) {
            int count = expected ? 1 : 0;
            check(InputMonitorCompat.active == count, "wrong active monitor count");
            check(InputMonitorCompat.receivers.size() == count, "wrong active receiver count");
            check(WindowInfosListenerForTest.listeners == count, "wrong window listener count");
        }
    }

    private interface Test { void run() throws Exception; }
    private record Case(String name, Test test) {}

    public static void main(String[] args) {
        List<Case> cases = new ArrayList<>(List.of(
                new Case("home double tap still sleeps once after the delay", () -> {
                    Fixture f = new Fixture();
                    f.monitoring(true);
                    f.doubleTap();
                    f.awake();
                    f.finishSleepDelay();
                    check(f.power.sleeps == 1, "home gesture did not sleep exactly once");
                }),
                new Case("QS already open at startup never registers home input", () -> {
                    Fixture f = new Fixture(true, true);
                    f.monitoring(false);
                    f.doubleTap(); f.doubleTap();
                    f.finishSleepDelay(); f.awake();
                }),
                new Case("shade opening releases input before rapid tile taps", () -> {
                    Fixture f = new Fixture();
                    f.shade(true);
                    f.monitoring(false);
                    f.doubleTap(); f.doubleTap();
                    f.finishSleepDelay(); f.awake();
                }),
                new Case("shade opening cancels a queued home sleep", () -> {
                    Fixture f = new Fixture();
                    f.doubleTap();
                    check(f.main.pendingCount() == 1, "no sleep was queued");
                    f.shade(true);
                    check(f.main.pendingCount() == 0, "sleep callback remained queued");
                    f.finishSleepDelay(); f.awake();
                }),
                new Case("delayed sleep reads current shade state before collector delivery", () -> {
                    Fixture f = new Fixture();
                    f.doubleTap();
                    f.expanded.holdDelivery = true;
                    f.expanded.setValue(true);
                    f.finishSleepDelay(); f.awake();
                }),
                new Case("input reads current shade state before collector delivery", () -> {
                    Fixture f = new Fixture();
                    f.expanded.holdDelivery = true;
                    f.expanded.setValue(true);
                    f.doubleTap();
                    // Clear the shade before a wrongly queued callback would fire.
                    f.expanded.setValue(false);
                    f.finishSleepDelay(); f.awake();
                }),
                new Case("shade round trip discards the previous home tap", () -> {
                    Fixture f = new Fixture();
                    f.tap();
                    f.shade(true);
                    f.shade(false);
                    f.monitoring(true);
                    f.main.advanceBy(80); f.tap();
                    check(f.main.pendingCount() == 0, "tap paired across the shade session");
                    f.main.advanceBy(80); f.tap();
                    f.finishSleepDelay();
                    check(f.power.sleeps == 1, "fresh home double tap did not work");
                }),
                new Case("tile tap cannot pair with the first home tap", () -> {
                    Fixture f = new Fixture(true, false);
                    f.tap();
                    f.shade(false);
                    f.main.advanceBy(80); f.tap();
                    f.finishSleepDelay(); f.awake();
                }),
                new Case("repeated shade sessions do not leak monitors or listeners", () -> {
                    Fixture f = new Fixture();
                    for (int i = 0; i < 5; i++) {
                        f.shade(true); f.monitoring(false);
                        f.shade(true); f.monitoring(false);
                        f.shade(false); f.monitoring(true);
                        f.shade(false); f.monitoring(true);
                    }
                    check(InputMonitorCompat.created == 6, "duplicate or missing monitor registration");
                }),
                new Case("other focused apps remain excluded", () -> {
                    Fixture f = new Fixture();
                    ActivityTaskManager.focused.topActivity = new ComponentName("example.app");
                    TaskStackChangeListeners.getInstance().changed();
                    f.main.drain(); f.monitoring(false);
                    f.doubleTap(); f.finishSleepDelay(); f.awake();
                }),
                new Case("falsing still rejects accidental double taps", () -> {
                    Fixture f = new Fixture();
                    f.falsing.falseDoubleTap = true;
                    f.doubleTap(); f.finishSleepDelay(); f.awake();
                }),
                new Case("excluded screen regions remain excluded", () -> {
                    Fixture f = new Fixture();
                    for (int y : new int[] {100, 2300}) {
                        f.tap(500, y, 1); f.main.advanceBy(80); f.tap(500, y, 1);
                        f.finishSleepDelay(); f.awake();
                    }
                }),
                new Case("multiple pointers do not trigger home sleep", () -> {
                    Fixture f = new Fixture();
                    f.tap(500, 800, 2); f.main.advanceBy(80); f.tap(500, 800, 2);
                    f.finishSleepDelay(); f.awake();
                })
        ));
        for (String exclusion : List.of("overview", "keyboard", "bubble", "disabled setting")) {
            cases.add(new Case(exclusion + " still cancels pending home sleep", () -> {
                Fixture f = new Fixture();
                f.doubleTap();
                switch (exclusion) {
                    case "overview" -> f.launcher.overview(true);
                    case "keyboard" -> f.commands.ime(true);
                    case "bubble" -> f.controller.onBubbleExpandChanged(true);
                    case "disabled setting" -> f.tuner.setEnabled(false);
                    default -> throw new AssertionError(exclusion);
                }
                f.main.drain(); f.monitoring(false);
                f.finishSleepDelay(); f.awake();
                // Collapsing QS must not override another reason to reject the home gesture.
                f.shade(true); f.shade(false); f.monitoring(false);
            }));
        }
        int passed = 0, failed = 0;
        for (Case test : cases) {
            try {
                test.test.run(); passed++;
                System.out.println("PASS " + test.name);
            } catch (Throwable error) {
                failed++;
                System.out.println("FAIL " + test.name + ": " + error);
            }
        }
        System.out.println("passed=" + passed + " failed=" + failed);
        if (failed != 0) System.exit(1);
    }
}
