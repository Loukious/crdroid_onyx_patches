"""Minimal host boundaries for compiling the complete production DT2S class.

The main-loop queue, StateFlow delivery, input monitor disposal and sleep calls
are observable. Gesture recognition is a two-tap model, not Android's detector.
No production eligibility, cancellation or lifecycle behavior is copied here.
"""

TYPES = {
    "android.app.ActivityManager": """
public class ActivityManager { public static class RunningTaskInfo extends TaskInfo {} }
""",
    "android.app.ActivityTaskManager": """
public class ActivityTaskManager {
    public static TaskInfo focused;
    public static class Service {
        public TaskInfo getFocusedRootTaskInfo() throws android.os.RemoteException { return focused; }
    }
    public static Service getService() { return new Service(); }
}
""",
    "android.app.TaskInfo": """
public class TaskInfo {
    public android.content.ComponentName topActivity;
    public int activityType;
    public int getActivityType() { return activityType; }
}
""",
    "android.app.WindowConfiguration": """
public class WindowConfiguration { public static final int ACTIVITY_TYPE_HOME = 2; }
""",
    "android.content.ComponentName": """
public class ComponentName {
    private final String name;
    public ComponentName(String name) { this.name = name; }
    public String getPackageName() { return name; }
}
""",
    "android.content.Context": """
public class Context {
    public android.content.res.Resources getResources() { return new android.content.res.Resources(); }
}
""",
    "android.content.res.Resources": """
public class Resources {
    public boolean getBoolean(int id) { return true; }
    public android.util.DisplayMetrics getDisplayMetrics() { return new android.util.DisplayMetrics(); }
}
""",
    "android.graphics.Matrix": """
public class Matrix { public boolean invert(Matrix other) { return true; } public void mapPoints(float[] p) {} }
""",
    "android.graphics.Rect": """
public class Rect { public int bottom; public boolean isEmpty() { return bottom <= 0; } }
""",
    "android.graphics.Region": """
public class Region { public boolean contains(int x, int y) { return x >= 0 && x < 1080 && y >= 0 && y < 2400; } }
""",
    "android.inputmethodservice.InputMethodService": """
public class InputMethodService { public static final int IME_VISIBLE = 2; }
""",
    "android.os.Handler": """
public class Handler {
    private record Task(Runnable action, long at) {}
    private final java.util.List<Task> tasks = new java.util.ArrayList<>();
    public boolean post(Runnable r) { return postDelayed(r, 0); }
    public boolean postDelayed(Runnable r, long delay) { tasks.add(new Task(r, SystemClock.now + delay)); return true; }
    public void removeCallbacks(Runnable r) { tasks.removeIf(t -> t.action == r); }
    public boolean hasCallbacks(Runnable r) { return tasks.stream().anyMatch(t -> t.action == r); }
    public Looper getLooper() { return new Looper(); }
    public int pendingCount() { return tasks.size(); }
    public void drain() {
        for (int i = 0; i < 1000; i++) {
            Task next = tasks.stream().filter(t -> t.at <= SystemClock.now)
                    .min(java.util.Comparator.comparingLong(Task::at)).orElse(null);
            if (next == null) return;
            tasks.remove(next);
            next.action.run();
        }
        throw new AssertionError("main loop did not become idle");
    }
    public void advanceBy(long delay) { SystemClock.now += delay; drain(); }
}
""",
    "android.os.Looper": "public class Looper {}",
    "android.os.PowerManager": """
public class PowerManager { public int sleeps; public void goToSleep(long time) { sleeps++; } }
""",
    "android.os.RemoteException": "public class RemoteException extends Exception {}",
    "android.os.SystemClock": """
public class SystemClock { public static long now; public static long uptimeMillis() { return now; } }
""",
    "android.util.DisplayMetrics": """
public class DisplayMetrics { public float density = 2; public int heightPixels = 2400, widthPixels = 1080; }
""",
    "android.util.Log": """
public class Log {
    public static int d(String tag, String text) { return 0; }
    public static int w(String tag, String text) { return 0; }
    public static int e(String tag, String text) { return 0; }
}
""",
    "android.view.Choreographer": """
public class Choreographer { public static Choreographer getInstance() { return new Choreographer(); } }
""",
    "android.view.Display": "public class Display { public static final int DEFAULT_DISPLAY = 0; }",
    "android.view.InputEvent": "public class InputEvent {}",
    "android.view.MotionEvent": """
public class MotionEvent extends InputEvent {
    public static final int ACTION_DOWN = 0, ACTION_UP = 1, ACTION_CANCEL = 3;
    private final int action, pointers;
    private final float x, y;
    public MotionEvent(int action, int pointers, float x, float y) {
        this.action = action; this.pointers = pointers; this.x = x; this.y = y;
    }
    public int getActionMasked() { return action; }
    public int getPointerCount() { return pointers; }
    public float getRawX() { return x; }
    public float getRawY() { return y; }
}
""",
    "android.view.GestureDetector": """
public class GestureDetector {
    public static class SimpleOnGestureListener { public boolean onDoubleTapEvent(MotionEvent e) { return false; } }
    private final SimpleOnGestureListener listener;
    private long lastUp = -1;
    public GestureDetector(android.content.Context context, SimpleOnGestureListener listener) { this.listener = listener; }
    public void setIsLongpressEnabled(boolean enabled) {}
    public boolean onTouchEvent(MotionEvent e) {
        if (e.getActionMasked() == MotionEvent.ACTION_CANCEL) lastUp = -1;
        if (e.getActionMasked() != MotionEvent.ACTION_UP) return false;
        long now = android.os.SystemClock.now;
        if (lastUp >= 0 && now - lastUp <= 300) { lastUp = -1; return listener.onDoubleTapEvent(e); }
        lastUp = now;
        return false;
    }
}
""",
    "android.window.WindowInfosListenerForTest": """
public class WindowInfosListenerForTest {
    public static class DisplayInfo { public int displayId; public android.graphics.Matrix transform = new android.graphics.Matrix(); }
    public static class WindowInfo {
        public int displayId;
        public boolean isVisible = true, isTouchable = true, isTrustedOverlay;
        public String name;
        public android.graphics.Region touchableRegion = new android.graphics.Region();
        public WindowInfo(String name, boolean trusted) { this.name = name; this.isTrustedOverlay = trusted; }
    }
    public static java.util.List<WindowInfo> windows = java.util.List.of();
    public static int listeners;
    public void addWindowInfosListener(java.util.function.BiConsumer<java.util.List<WindowInfo>, java.util.List<DisplayInfo>> c) {
        listeners++; c.accept(windows, java.util.List.of(new DisplayInfo()));
    }
    public void removeWindowInfosListener(java.util.function.BiConsumer<java.util.List<WindowInfo>, java.util.List<DisplayInfo>> c) { listeners--; }
}
""",
    "com.android.systemui.CoreStartable": "public interface CoreStartable { void start(); }",
    "com.android.systemui.LauncherProxyService": """
public class LauncherProxyService {
    public interface LauncherProxyListener {
        default void onConnectionChanged(boolean connected) {}
        default void onOverviewVisibilityChanged(boolean visible) {}
    }
    private LauncherProxyListener listener;
    public void addCallback(LauncherProxyListener listener) { this.listener = listener; }
    public void overview(boolean visible) { listener.onOverviewVisibilityChanged(visible); }
}
""",
    "com.android.systemui.keyguard.KeyguardUnlockAnimationController": """
public class KeyguardUnlockAnimationController {
    public com.android.systemui.shared.system.smartspace.SmartspaceState getLauncherSmartspaceState() { return null; }
}
""",
    "com.android.systemui.keyguard.KeyguardWmStateRefactor": """
public class KeyguardWmStateRefactor { public static boolean isEnabled() { return false; } }
""",
    "com.android.systemui.keyguard.data.repository.InWindowLauncherUnlockAnimationRepository": """
public class InWindowLauncherUnlockAnimationRepository {
    public kotlinx.coroutines.flow.StateFlow<com.android.systemui.shared.system.smartspace.SmartspaceState> getLauncherSmartspaceState() {
        return new kotlinx.coroutines.flow.StateFlow<>(null);
    }
}
""",
    "com.android.systemui.plugins.FalsingManager": """
public class FalsingManager { public boolean falseDoubleTap; public boolean isFalseDoubleTap() { return falseDoubleTap; } }
""",
    "com.android.systemui.shade.domain.interactor.ShadeInteractor": """
public class ShadeInteractor {
    private final kotlinx.coroutines.flow.StateFlow<Boolean> expanded;
    public ShadeInteractor(kotlinx.coroutines.flow.StateFlow<Boolean> expanded) { this.expanded = expanded; }
    public kotlinx.coroutines.flow.StateFlow<Boolean> isAnyExpanded() { return expanded; }
}
""",
    "kotlinx.coroutines.Job": "public class Job {}",
    "kotlinx.coroutines.flow.Flow": """
public interface Flow<T> { void subscribe(android.os.Handler handler, java.util.function.Consumer<T> consumer); }
""",
    "kotlinx.coroutines.flow.StateFlow": """
public class StateFlow<T> implements Flow<T> {
    private T value;
    private final java.util.List<Runnable> deliveries = new java.util.ArrayList<>();
    public boolean holdDelivery;
    public StateFlow(T initial) { value = initial; }
    public T getValue() { return value; }
    public void subscribe(android.os.Handler handler, java.util.function.Consumer<T> consumer) {
        Runnable deliver = () -> handler.post(() -> consumer.accept(value));
        deliveries.add(deliver);
        if (!holdDelivery) deliver.run();
    }
    public void setValue(T next) { value = next; if (!holdDelivery) deliveries.forEach(Runnable::run); }
    public void deliverCurrent() { deliveries.forEach(Runnable::run); }
}
""",
    "com.android.systemui.util.kotlin.JavaAdapter": """
public class JavaAdapter {
    private final android.os.Handler handler;
    public JavaAdapter(android.os.Handler handler) { this.handler = handler; }
    public <T> kotlinx.coroutines.Job alwaysCollectFlow(kotlinx.coroutines.flow.Flow<T> flow, java.util.function.Consumer<T> consumer) {
        flow.subscribe(handler, consumer); return new kotlinx.coroutines.Job();
    }
}
""",
    "com.android.systemui.shared.system.InputChannelCompat": """
public class InputChannelCompat {
    public static class InputEventReceiver {
        public final java.util.function.Consumer<android.view.InputEvent> listener;
        public InputEventReceiver(java.util.function.Consumer<android.view.InputEvent> listener) { this.listener = listener; }
        public void dispose() { InputMonitorCompat.receivers.remove(this); }
    }
}
""",
    "com.android.systemui.shared.system.InputMonitorCompat": """
public class InputMonitorCompat {
    public static int active, created;
    public static final java.util.List<InputChannelCompat.InputEventReceiver> receivers = new java.util.ArrayList<>();
    public InputMonitorCompat(String name, int display) { active++; created++; }
    public InputChannelCompat.InputEventReceiver getInputReceiver(android.os.Looper looper, android.view.Choreographer choreographer,
            java.util.function.Consumer<android.view.InputEvent> listener) {
        var receiver = new InputChannelCompat.InputEventReceiver(listener); receivers.add(receiver); return receiver;
    }
    public void dispose() { active--; }
    public static void dispatch(android.view.InputEvent event) {
        for (var receiver : java.util.List.copyOf(receivers)) receiver.listener.accept(event);
    }
    public static void reset() { active = 0; created = 0; receivers.clear(); }
}
""",
    "com.android.systemui.shared.system.TaskStackChangeListener": """
public class TaskStackChangeListener {
    public void onTaskStackChanged() {}
    public void onTaskMovedToFront(android.app.ActivityManager.RunningTaskInfo taskInfo) {}
}
""",
    "com.android.systemui.shared.system.TaskStackChangeListeners": """
public class TaskStackChangeListeners {
    private static final TaskStackChangeListeners instance = new TaskStackChangeListeners();
    private TaskStackChangeListener listener;
    public static TaskStackChangeListeners getInstance() { return instance; }
    public void registerTaskStackListener(TaskStackChangeListener listener) { this.listener = listener; }
    public void changed() { listener.onTaskStackChanged(); }
}
""",
    "com.android.systemui.shared.system.smartspace.SmartspaceState": """
public class SmartspaceState {
    public boolean getVisibleOnScreen() { return false; }
    public android.graphics.Rect getBoundsOnScreen() { return new android.graphics.Rect(); }
}
""",
    "com.android.systemui.statusbar.CommandQueue": """
public class CommandQueue {
    public interface Callbacks { default void setImeWindowStatus(int display, int vis, int back, boolean switcher) {} }
    private Callbacks callbacks;
    public void addCallback(Callbacks callbacks) { this.callbacks = callbacks; }
    public void ime(boolean visible) { callbacks.setImeWindowStatus(0, visible ? 2 : 0, 0, false); }
}
""",
    "com.android.systemui.tuner.TunerService": """
public class TunerService {
    public interface Tunable { void onTuningChanged(String key, String value); }
    private Tunable tunable;
    private String key;
    public void addTunable(Tunable tunable, String key) { this.tunable = tunable; this.key = key; setEnabled(true); }
    public void setEnabled(boolean enabled) { tunable.onTuningChanged(key, enabled ? "1" : "0"); }
    public static boolean parseIntegerSwitch(String value, boolean fallback) { return value == null ? fallback : Integer.parseInt(value) != 0; }
}
""",
    "com.android.wm.shell.shared.FocusTransitionListener": """
public interface FocusTransitionListener {
    void onFocusedTaskChanged(android.app.ActivityManager.RunningTaskInfo task, boolean onDisplay, boolean globally);
    void onFocusedDisplayChanged(int display);
}
""",
    "com.android.wm.shell.shared.ShellTransitions": """
public class ShellTransitions { public void setFocusTransitionListener(FocusTransitionListener listener, java.util.concurrent.Executor executor) {} }
""",
    "dagger.Lazy": "public interface Lazy<T> { T get(); }",
    "lineageos.providers.LineageSettings": """
public class LineageSettings { public static class System { public static final String DOUBLE_TAP_SLEEP_GESTURE = "double_tap_sleep_gesture"; } }
""",
    "org.lineageos.platform.internal.R": """
public class R { public static class bool { public static final int config_dt2sGestureEnabledByDefault = 1; } }
""",
}

for name in ("javax.inject.Inject", "com.android.systemui.dagger.SysUISingleton",
             "com.android.systemui.dagger.qualifiers.Background",
             "com.android.systemui.dagger.qualifiers.Main"):
    TYPES[name] = f"public @interface {name.rsplit('.', 1)[1]} {{}}"

SOURCES = {
    name.replace(".", "/") + ".java": "package " + name.rsplit(".", 1)[0] + ";\n" + body
    for name, body in TYPES.items()
}
