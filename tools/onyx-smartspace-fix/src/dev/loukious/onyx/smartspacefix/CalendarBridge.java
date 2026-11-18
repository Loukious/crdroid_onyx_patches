package dev.loukious.onyx.smartspacefix;

import android.app.Application;
import android.app.appsearch.AppSearchResult;
import android.app.appsearch.SearchResult;
import android.app.appsearch.SearchResults;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.Handler;
import android.os.HandlerThread;
import android.util.Log;

import java.lang.ref.WeakReference;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashMap;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.WeakHashMap;
import java.util.concurrent.Executor;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;

/** ROM-packaged calendar correction called directly from the examined C.9 classes. */
public final class CalendarBridge {
    private static final String PACKAGE = "com.google.android.as";
    private static final String TAG = "OnyxSmartspace";
    // Native C.9 calendar templates, shared with its notification calendar renderer.
    private static final int CALENDAR_EVENT_DURING = 0x7f1400f0;
    private static final int CALENDAR_EVENT_PRE = 0x7f1400f1;
    private static final int DURATION_MIN = 0x7f120004;
    private static final Object LOCK = new Object();
    private static final Map<Object, Provider> PROVIDERS = new WeakHashMap<>();
    private static final Map<Object, Boolean> FULL_SEARCHES = new WeakHashMap<>();
    private static volatile Contract contract;
    private static volatile Handler handler;

    private CalendarBridge() {}

    public static void initialize(Object provider, Context context) {
        try {
            if (provider == null || !"sam".equals(provider.getClass().getName())) return;
            if (context == null) context = (Context)field(provider.getClass(), "b").get(provider);
            if (!boot(context, provider.getClass().getClassLoader())) return;
            state(provider);
        } catch (Throwable failure) { error("initialization", failure); }
    }

    public static void beforeRefresh(Object provider, Object continuation) {
        try {
            Provider state = state(provider);
            if (state == null) return;
            Contract api = contract;
            // sal marks coroutine re-entry before sam.v removes the high bit.
            if (api.resumeClass.isInstance(continuation) && api.resumeState.getInt(continuation) < 0) return;
            synchronized (state) {
                state.entries.clear();
                state.cancelBoundary();
                state.cancelPublication();
                state.pendingPublication = false;
            }
        } catch (Throwable failure) { error("refresh", failure); }
    }

    public static void beforeUpsert(Object provider, List<?> values) {
        try {
            Provider state = state(provider);
            if (state == null || values == null) return;
            Contract api = contract;
            long now = System.currentTimeMillis();
            synchronized (state) {
                state.expireSuppression(now);
                for (Object value : values) {
                    if (!api.calendarClass.isInstance(value)) continue;
                    try {
                        Entry entry = entry(value);
                        if (entry.windowStart < entry.expiry() && entry.expiry() > now
                                && !state.suppressed.containsKey(entry.id)) {
                            state.entries.put(entry.id, entry);
                        } else state.entries.remove(entry.id);
                    } catch (Throwable failure) { error("calendar conversion", failure); }
                }
            }
        } catch (Throwable failure) { error("upsert", failure); }
    }

    /** Extends only the examined timed CalendarEvent window before native TTL filtering. */
    public static List<?> normalizeCalendarEntries(Object provider, List<?> values) {
        if (values == null) return null;
        try {
            if (state(provider) == null) return values;
            Contract api = contract;
            List<Object> normalized = new ArrayList<>(values.size());
            for (Object value : values) {
                Object replacement = value;
                if (api.calendarClass.isInstance(value)) {
                    try { replacement = extendTimedEvent(value); }
                    catch (Throwable failure) { error("event lifetime", failure); }
                }
                normalized.add(replacement);
            }
            return normalized;
        } catch (Throwable failure) {
            error("event normalization", failure);
            return values;
        }
    }

    private static Object extendTimedEvent(Object value) throws Throwable {
        Contract api = contract;
        if (api.calendarAllDay.getBoolean(value)) return value;
        Object endDate = api.calendarEnd.get(value);
        if (endDate == null) return value;
        long start = time(api.calendarStart.get(value));
        long end = time(endDate);
        if (end <= start) return value;
        Object metadata = invoke(api.calendarMetadata, value);
        long begin = time(api.windowStart.get(metadata));
        long expiry = time(api.windowEnd.get(metadata));
        long created = time(api.metadataCreated.get(metadata));
        // Other calendar sources may have their own windows or dismissal lifetimes.
        // Match the C.9 AppSearch converter's exact 30-minute/start-time metadata.
        if (expiry != start || Math.subtractExact(start, begin) != 30L * 60 * 1000
                || api.metadataTtl.getLong(metadata) != Math.subtractExact(start, created)) {
            return value;
        }
        Object newEnd = invoke(api.instantParse, null, String.valueOf(endDate));
        Object extended = construct(api.metadataConstructor,
                api.metadataId.get(metadata), api.metadataInstance.get(metadata),
                api.metadataAttribution.get(metadata), api.metadataCreated.get(metadata),
                Long.valueOf(Math.subtractExact(end, created)), api.windowStart.get(metadata),
                newEnd, Double.valueOf(api.metadataConfidence.getDouble(metadata)),
                api.metadataImportantTimes.get(metadata));
        return construct(api.calendarConstructor,
                api.calendarName.get(value), api.calendarUrl.get(value),
                api.calendarStart.get(value), endDate, Boolean.FALSE, api.calendarLocation.get(value),
                api.calendarType.get(value), extended, api.calendarDedupe.get(value),
                api.calendarTap.get(value), api.calendarDismiss.get(value), api.calendarSeen.get(value));
    }

    public static void afterUpsert(Object provider) {
        try { requestPublication(state(provider)); }
        catch (Throwable failure) { error("upsert publication", failure); }
    }

    public static void beforeRemove(Object provider, List<?> ids) {
        try {
            if (ids == null || inProviderMethod("n")) return;
            Provider state = state(provider);
            if (state == null) return;
            synchronized (state) {
                for (Object id : ids) state.entries.remove(String.valueOf(id));
            }
        } catch (Throwable failure) { error("removal", failure); }
    }

    public static void afterRemove(Object provider) {
        try {
            // j schedules its own next boundary; n only prunes generated cards.
            if (!inProviderMethod("n") && !inProviderMethod("j")) requestPublication(state(provider));
        } catch (Throwable failure) { error("removal publication", failure); }
    }

    public static void beforeSelect(Object provider) {
        try {
            Provider state = state(provider);
            if (state == null || !calendarEnabled(provider)) return;
            Map<Object, Object> cache = cache(provider);
            long now = System.currentTimeMillis();
            synchronized (state) {
                state.expireSuppression(now);
                Iterator<Entry> retained = state.entries.values().iterator();
                while (retained.hasNext()) {
                    Entry entry = retained.next();
                    if (entry.expiry() <= now || state.suppressed.containsKey(entry.id)) retained.remove();
                    else cache.put(entry.id, entry.value);
                }
            }
        } catch (Throwable failure) { error("candidate retention", failure); }
    }

    public static Object afterSelect(Object provider, boolean force, Object result) {
        try {
            Provider state = state(provider);
            Contract api = contract;
            if (state == null || !api.resultClass.isInstance(result)) return result;
            List<?> original = (List<?>)api.resultPairs.get(result);
            List<Entry> candidates = new ArrayList<>();
            long now = System.currentTimeMillis();
            if (calendarEnabled(provider)) {
                // Native j has already applied its TTL and seen-expiry removals.
                synchronized (state) {
                    for (Object value : cache(provider).values()) {
                        if (!api.calendarClass.isInstance(value)) continue;
                        Entry entry = entry(value);
                        if (!state.suppressed.containsKey(entry.id)) candidates.add(entry);
                    }
                }
            }
            CalendarPolicy.Decision decision = CalendarPolicy.choose(candidates, now);
            Entry best = (Entry)decision.best;
            Object chosen = null;
            if (best != null) {
                Object displayValue = displayCalendarEntry(best,
                        (Context)field(provider.getClass(), "b").get(provider), now);
                for (Object pair : original) {
                    if (displayValue.equals(api.pairValue.get(pair))) { chosen = pair; break; }
                }
                if (chosen == null) {
                    boolean changed = force;
                    if (!changed) {
                        changed = true;
                        Object previous = invoke(api.flowGet, api.providerFlow.get(provider));
                        if (api.resultClass.isInstance(previous)) {
                            for (Object pair : (List<?>)api.resultPairs.get(previous)) {
                                if (displayValue.equals(api.pairValue.get(pair))) { changed = false; break; }
                            }
                        }
                    }
                    chosen = construct(api.pairConstructor, Boolean.valueOf(changed), displayValue);
                }
            }
            List<Object> selected = new ArrayList<>();
            boolean inserted = false;
            for (Object pair : original) {
                if (!api.calendarClass.isInstance(api.pairValue.get(pair))) selected.add(pair);
                else if (best != null && !inserted) { selected.add(chosen); inserted = true; }
            }
            if (best != null && !inserted) selected.add(chosen);
            Object replacement = construct(api.resultConstructor, selected);
            boolean publish;
            synchronized (state) {
                state.scheduleBoundary(decision.nextBoundary, now);
                publish = state.pendingPublication;
                state.pendingPublication = false;
                String status = "retained=" + state.entries.size() + " calendarCards=" + (best == null ? 0 : 1)
                        + " start=" + (best == null ? "none" : best.start) + " nextBoundary=" + decision.nextBoundary;
                if (!status.equals(state.lastStatus)) { Log.i(TAG, status); state.lastStatus = status; }
            }
            if (publish) invoke(api.flowSet, api.providerFlow.get(provider), replacement);
            return replacement;
        } catch (Throwable failure) {
            error("selection", failure);
            return result;
        }
    }

    public static void beforeDismiss(Object provider, Object targetEvent) {
        try {
            Provider state = state(provider);
            if (state == null) return;
            Contract api = contract;
            if (!api.eventClass.isInstance(targetEvent)
                    || !Integer.valueOf(4).equals(invoke(api.eventType, targetEvent))) return;
            Object target = invoke(api.eventTarget, targetEvent);
            if (target == null) return;
            String id = (String)invoke(api.targetId, target);
            synchronized (state) {
                Entry entry = state.entries.remove(id);
                if (entry != null) {
                    state.suppressed.put(id, entry.expiry());
                    state.dismissalEvents.put(targetEvent, Boolean.TRUE);
                }
            }
        } catch (Throwable failure) { error("dismissal", failure); }
    }

    public static void afterDismiss(Object provider, Object targetEvent) {
        try {
            if (targetEvent == null) return;
            Provider state = state(provider);
            if (state == null) return;
            boolean changed;
            synchronized (state) { changed = Boolean.TRUE.equals(state.dismissalEvents.remove(targetEvent)); }
            if (changed) requestPublication(state);
        } catch (Throwable failure) { error("dismissal publication", failure); }
    }

    public static void markSearch(Object ud, String query) {
        try {
            if (ud == null || !"ud".equals(ud.getClass().getName())) return;
            synchronized (FULL_SEARCHES) {
                if ("".equals(query)) FULL_SEARCHES.put(ud, Boolean.TRUE);
                else FULL_SEARCHES.remove(ud);
            }
        } catch (Throwable failure) { error("query marking", failure); }
    }

    /** Null preserves the original native page implementation. */
    public static Object readAllPages(Object ud) {
        try {
            if (ud == null) return null;
            synchronized (FULL_SEARCHES) {
                if (!Boolean.TRUE.equals(FULL_SEARCHES.get(ud))) return null;
            }
            Context context = (Context)field(ud.getClass(), "b").get(ud);
            if (!boot(context, ud.getClass().getClassLoader())) return null;
            Contract api = contract;
            if (!api.readClass.isInstance(ud)) return null;
            Object spec = api.readSpec.get(ud);
            if (!((Collection<?>)invoke(api.schemas, spec)).contains("CalendarEvent")) return null;
            PageRead read;
            synchronized (FULL_SEARCHES) {
                if (!Boolean.TRUE.equals(FULL_SEARCHES.get(ud))) return null;
                read = new PageRead(ud);
                // The flattened result belongs to the native caller's first read.
                FULL_SEARCHES.remove(ud);
            }
            read.start();
            return read.future;
        } catch (Throwable failure) {
            error("page setup", failure);
            return null;
        }
    }

    private static boolean boot(Context context, ClassLoader loader) throws Throwable {
        if (context == null || !PACKAGE.equals(context.getPackageName())
                || !PACKAGE.equals(Application.getProcessName())) return false;
        Contract current = contract;
        if (current != null) return current.loader == loader;
        synchronized (LOCK) {
            current = contract;
            if (current != null) return current.loader == loader;
            Contract resolved = new Contract(loader);
            HandlerThread worker = new HandlerThread(TAG);
            worker.start();
            Handler targetHandler = new Handler(worker.getLooper());
            try {
                IntentFilter changes = new IntentFilter();
                changes.addAction(Intent.ACTION_SCREEN_ON);
                changes.addAction(Intent.ACTION_USER_PRESENT);
                changes.addAction(Intent.ACTION_TIME_CHANGED);
                changes.addAction(Intent.ACTION_TIMEZONE_CHANGED);
                changes.addAction(Intent.ACTION_DATE_CHANGED);
                Context app = context.getApplicationContext();
                (app == null ? context : app).registerReceiver(new BroadcastReceiver() {
                    @Override public void onReceive(Context unused, Intent intent) {
                        List<Provider> current;
                        synchronized (LOCK) { current = new ArrayList<>(PROVIDERS.values()); }
                        for (Provider state : current) requestPublication(state);
                    }
                }, changes, null, targetHandler, Context.RECEIVER_NOT_EXPORTED);
                handler = targetHandler;
                contract = resolved;
                Log.i(TAG, "Enabled ROM calendar bridge for verified C.9 contract");
                return true;
            } catch (Throwable failure) {
                worker.quitSafely();
                throw failure;
            }
        }
    }

    private static Provider state(Object provider) throws Throwable {
        if (provider == null || !"sam".equals(provider.getClass().getName())) return null;
        Contract api = contract;
        if (api == null) {
            Context context = (Context)field(provider.getClass(), "b").get(provider);
            if (!boot(context, provider.getClass().getClassLoader())) return null;
            api = contract;
        }
        if (!api.providerClass.isInstance(provider)) return null;
        synchronized (LOCK) {
            Provider state = PROVIDERS.get(provider);
            if (state == null) { state = new Provider(provider); PROVIDERS.put(provider, state); }
            return state;
        }
    }

    private static Entry entry(Object value) throws Throwable {
        Contract api = contract;
        Object metadata = invoke(api.calendarMetadata, value);
        return new Entry(value, (String)api.metadataId.get(metadata), time(api.calendarStart.get(value)),
                api.calendarEnd.get(value) == null ? time(api.calendarStart.get(value))
                        : time(api.calendarEnd.get(value)),
                time(api.windowStart.get(metadata)), time(api.windowEnd.get(metadata)));
    }

    private static Object displayCalendarEntry(Entry entry, Context context, long now) throws Throwable {
        Contract api = contract;
        Object value = entry.value;
        Object metadata = invoke(api.calendarMetadata, value);
        // Decorate only the normalized AppSearch timed-event path. Keep notification
        // calendar cards, all-day events and their existing title formats untouched.
        if (api.calendarAllDay.getBoolean(value) || entry.end <= entry.start
                || entry.windowEnd != entry.end
                || Math.subtractExact(entry.start, entry.windowStart) != 30L * 60 * 1000
                || !"".equals(api.calendarDedupe.get(value))
                || api.metadataTtl.getLong(metadata) != Math.subtractExact(entry.end,
                        time(api.metadataCreated.get(metadata)))) {
            return value;
        }
        String originalTitle = (String)api.calendarName.get(value);
        long minutes = CalendarPolicy.minutesUntilStart(entry.start, now);
        String title;
        if (minutes == 0) {
            title = context.getString(CALENDAR_EVENT_DURING, originalTitle);
        } else {
            int quantity = (int)Math.min(minutes, Integer.MAX_VALUE);
            String duration = context.getResources().getQuantityString(DURATION_MIN, quantity, quantity);
            title = context.getString(CALENDAR_EVENT_PRE, originalTitle, duration);
        }
        return copyCalendar(value, metadata, title);
    }

    private static Object copyCalendar(Object value, Object metadata, String title) throws Throwable {
        Contract api = contract;
        return construct(api.calendarConstructor, title, api.calendarUrl.get(value),
                api.calendarStart.get(value), api.calendarEnd.get(value),
                Boolean.valueOf(api.calendarAllDay.getBoolean(value)), api.calendarLocation.get(value),
                api.calendarType.get(value), metadata, api.calendarDedupe.get(value),
                api.calendarTap.get(value), api.calendarDismiss.get(value), api.calendarSeen.get(value));
    }

    private static long time(Object value) { return Instant.parse(String.valueOf(value)).toEpochMilli(); }

    private static boolean calendarEnabled(Object provider) throws Throwable {
        Contract api = contract;
        return Boolean.TRUE.equals(invoke(api.settingsEnabled, api.providerSettings.get(provider), api.calendarClass));
    }

    @SuppressWarnings("unchecked")
    private static Map<Object, Object> cache(Object provider) throws IllegalAccessException {
        return (Map<Object, Object>)contract.providerCache.get(provider);
    }

    private static boolean inProviderMethod(String name) {
        for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
            if ("sam".equals(frame.getClassName()) && name.equals(frame.getMethodName())) return true;
        }
        return false;
    }

    private static void requestPublication(Provider state) {
        requestPublication(state, false);
    }

    private static void requestPublication(Provider state, boolean force) {
        if (state == null) return;
        synchronized (state) {
            state.forcePublication |= force;
            if (state.publicationTask != null) return;
            state.publicationTask = new Runnable() {
                @Override public void run() {
                    Object owner;
                    boolean forced;
                    synchronized (state) {
                        if (state.publicationTask != this) return;
                        state.publicationTask = null;
                        owner = state.owner.get();
                        state.pendingPublication = owner != null;
                        forced = state.forcePublication;
                        state.forcePublication = false;
                    }
                    if (owner == null) return;
                    try { invoke(contract.select, owner, Boolean.valueOf(forced), contract.noOp); }
                    catch (Throwable failure) {
                        synchronized (state) { state.pendingPublication = false; }
                        error("publication", failure);
                    }
                }
            };
            if (!handler.post(state.publicationTask)) state.publicationTask = null;
        }
    }

    private static Field field(Class<?> type, String name) throws NoSuchFieldException {
        for (Class<?> current = type; current != null; current = current.getSuperclass()) {
            try {
                Field result = current.getDeclaredField(name);
                result.setAccessible(true);
                return result;
            } catch (NoSuchFieldException absent) { /* Search inherited fields. */ }
        }
        throw new NoSuchFieldException(name);
    }

    private static Method method(Class<?> type, String name, Class<?>... args) throws NoSuchMethodException {
        for (Class<?> current = type; current != null; current = current.getSuperclass()) {
            try {
                Method result = current.getDeclaredMethod(name, args);
                result.setAccessible(true);
                return result;
            } catch (NoSuchMethodException absent) { /* Search inherited methods. */ }
        }
        Method result = type.getMethod(name, args);
        result.setAccessible(true);
        return result;
    }

    private static Constructor<?> constructor(Class<?> type, Class<?>... args) throws NoSuchMethodException {
        Constructor<?> result = type.getDeclaredConstructor(args);
        result.setAccessible(true);
        return result;
    }

    private static Object invoke(Method method, Object receiver, Object... args) throws Throwable {
        try { return method.invoke(receiver, args); }
        catch (InvocationTargetException failure) { throw failure.getCause(); }
    }

    private static Object construct(Constructor<?> constructor, Object... args) throws Throwable {
        try { return constructor.newInstance(args); }
        catch (InvocationTargetException failure) { throw failure.getCause(); }
    }

    private static void error(String operation, Throwable failure) {
        Log.e(TAG, operation + ": " + failure.getClass().getSimpleName());
    }

    private static final class Provider {
        final WeakReference<Object> owner;
        final Map<String, Entry> entries = new HashMap<>();
        final Map<String, Long> suppressed = new HashMap<>();
        final Map<Object, Boolean> dismissalEvents = new WeakHashMap<>();
        Runnable boundary, publicationTask;
        boolean pendingPublication, forcePublication;
        String lastStatus;

        Provider(Object owner) { this.owner = new WeakReference<>(owner); }
        void expireSuppression(long now) {
            Iterator<Long> expired = suppressed.values().iterator();
            while (expired.hasNext()) if (expired.next() <= now) expired.remove();
        }
        void cancelBoundary() {
            if (boundary != null) handler.removeCallbacks(boundary);
            boundary = null;
        }
        void cancelPublication() {
            if (publicationTask != null) handler.removeCallbacks(publicationTask);
            publicationTask = null;
            forcePublication = false;
        }
        void scheduleBoundary(Long when, long now) {
            cancelBoundary();
            if (when == null || owner.get() == null) return;
            boundary = new Runnable() {
                @Override public void run() {
                    synchronized (Provider.this) {
                        if (boundary != this) return;
                        boundary = null;
                    }
                    requestPublication(Provider.this, true);
                }
            };
            if (!handler.postDelayed(boundary, CalendarPolicy.delay(now, when))) boundary = null;
        }
    }

    private static final class Entry extends CalendarPolicy.Candidate {
        final Object value;
        Entry(Object value, String id, long start, long end, long begin, long expiry) {
            super(id, start, end, begin, expiry);
            this.value = value;
        }
        long expiry() { return Math.min(end, windowEnd); }
    }

    /** Resolves the C.9 contract before activating any behavior, independent of versionCode. */
    private static final class Contract {
        final ClassLoader loader;
        final Class<?> providerClass, calendarClass, resultClass, readClass, resumeClass, eventClass;
        final Field providerCache, providerSettings, providerFlow, readSpec, readResults, readExecutor;
        final Field calendarStart, calendarEnd, calendarAllDay, calendarName, calendarUrl,
                calendarLocation, calendarType, calendarDedupe, calendarTap, calendarDismiss, calendarSeen;
        final Field metadataId, metadataInstance, metadataAttribution, metadataCreated, metadataTtl,
                metadataConfidence, metadataImportantTimes, windowStart, windowEnd, resultPairs,
                pairValue, resumeState;
        final Method select, settingsEnabled, calendarMetadata, schemas, flowGet, flowSet, callbackAccept, futureFail;
        final Method eventType, eventTarget, targetId, instantParse;
        final Constructor<?> resultConstructor, pairConstructor, futureConstructor, callbackConstructor,
                calendarConstructor, metadataConstructor;
        final Object noOp;

        Contract(ClassLoader loader) throws Throwable {
            this.loader = loader;
            providerClass = Class.forName("sam", false, loader);
            readClass = Class.forName("ud", false, loader);
            calendarClass = Class.forName("hil", false, loader);
            resultClass = Class.forName("rzm", false, loader);
            resumeClass = Class.forName("sal", false, loader);
            eventClass = Class.forName("android.app.smartspace.SmartspaceTargetEvent", false, loader);
            Class<?> targetClass = Class.forName("android.app.smartspace.SmartspaceTarget", false, loader);
            Class<?> pair = Class.forName("alrt", false, loader);
            Class<?> continuation = Class.forName("alus", false, loader);
            Class<?> settings = Class.forName("san", false, loader);
            Class<?> spec = Class.forName("sp", false, loader);
            Class<?> flow = Class.forName("amky", false, loader);
            Class<?> future = Class.forName("dgk", false, loader);
            Class<?> callback = Class.forName("uc", false, loader);
            Class<?> metadata = Class.forName("hiz", false, loader);
            providerCache = field(providerClass, "t");
            providerSettings = field(providerClass, "d");
            providerFlow = field(providerClass, "l");
            readSpec = field(readClass, "a");
            readResults = field(readClass, "d");
            readExecutor = field(readClass, "e");
            calendarStart = field(calendarClass, "b");
            calendarEnd = field(calendarClass, "c");
            calendarAllDay = field(calendarClass, "d");
            calendarName = field(calendarClass, "a");
            calendarUrl = field(calendarClass, "f");
            calendarLocation = field(calendarClass, "e");
            calendarType = field(calendarClass, "g");
            calendarDedupe = field(calendarClass, "i");
            calendarTap = field(calendarClass, "j");
            calendarDismiss = field(calendarClass, "k");
            calendarSeen = field(calendarClass, "l");
            metadataId = field(metadata, "a");
            metadataInstance = field(metadata, "b");
            metadataAttribution = field(metadata, "c");
            metadataCreated = field(metadata, "d");
            metadataTtl = field(metadata, "e");
            metadataConfidence = field(metadata, "h");
            metadataImportantTimes = field(metadata, "i");
            windowStart = field(metadata, "f");
            windowEnd = field(metadata, "g");
            resultPairs = field(resultClass, "a");
            pairValue = field(pair, "b");
            resumeState = field(resumeClass, "d");
            select = method(providerClass, "j", boolean.class, continuation);
            method(providerClass, "v", continuation);
            method(providerClass, "n", resultClass, continuation);
            method(providerClass, "y", List.class);
            method(providerClass, "x", List.class);
            method(providerClass, "c", String.class, eventClass, continuation);
            eventType = method(eventClass, "getEventType");
            eventTarget = method(eventClass, "getSmartspaceTarget");
            targetId = method(targetClass, "getSmartspaceTargetId");
            calendarMetadata = method(calendarClass, "c");
            settingsEnabled = method(settings, "j", Class.class);
            schemas = method(spec, "c");
            flowGet = method(flow, "c");
            flowSet = method(flow, "e", Object.class);
            callbackAccept = method(callback, "accept", Object.class);
            futureFail = method(future, "f", Throwable.class);
            resultConstructor = constructor(resultClass, List.class);
            pairConstructor = constructor(pair, Object.class, Object.class);
            futureConstructor = constructor(future);
            callbackConstructor = constructor(callback, readClass, future);
            noOp = field(Class.forName("amme", false, loader), "a").get(null);
            Class<?> instant = windowEnd.getType();
            instantParse = method(instant, "parse", CharSequence.class);
            metadataConstructor = constructor(metadata, String.class, String.class, String.class,
                    instant, long.class, instant, instant, double.class, List.class);
            calendarConstructor = constructor(calendarClass, String.class, String.class,
                    String.class, String.class, boolean.class, String.class, String.class,
                    metadata, String.class, Intent.class, Intent.class, Intent.class);
            if (select.getReturnType() != Object.class || calendarStart.getType() != String.class
                    || calendarEnd.getType() != String.class || calendarAllDay.getType() != boolean.class
                    || metadataId.getType() != String.class || resumeState.getType() != int.class
                    || !Map.class.isAssignableFrom(providerCache.getType())
                    || !List.class.isAssignableFrom(resultPairs.getType())
                    || readResults.getType() != SearchResults.class
                    || !Executor.class.isAssignableFrom(readExecutor.getType())
                    || !continuation.isInstance(noOp)) {
                throw new IllegalStateException("Unsupported calendar contract");
            }
        }
    }

    /** Drains asynchronously and uses uc for native SearchResult conversion. */
    private static final class PageRead implements Consumer<AppSearchResult<List<SearchResult>>> {
        final Object future, callback;
        final SearchResults search;
        final Executor executor;
        final List<SearchResult> combined = new ArrayList<>();
        final AtomicBoolean finished = new AtomicBoolean();
        final Runnable timeout = () -> fail(AppSearchResult.RESULT_INTERNAL_ERROR, "Calendar page read timed out");
        int pages, calendars;

        PageRead(Object owner) throws Throwable {
            Contract api = contract;
            future = construct(api.futureConstructor);
            callback = construct(api.callbackConstructor, owner, future);
            search = (SearchResults)api.readResults.get(owner);
            executor = (Executor)api.readExecutor.get(owner);
        }
        void start() {
            handler.postDelayed(timeout, 30000);
            try { search.getNextPage(executor, this); }
            catch (Throwable failure) { fail(AppSearchResult.RESULT_INTERNAL_ERROR, "Calendar page read failed"); }
        }
        @Override public void accept(AppSearchResult<List<SearchResult>> result) {
            if (finished.get()) return;
            try {
                if (!result.isSuccess()) { fail(result.getResultCode(), result.getErrorMessage()); return; }
                List<SearchResult> page = result.getResultValue();
                pages++;
                if (page.isEmpty()) {
                    if (finished.compareAndSet(false, true)) {
                        handler.removeCallbacks(timeout);
                        Log.i(TAG, "Calendar pages=" + pages + " records=" + calendars);
                        try { invoke(contract.callbackAccept, callback, AppSearchResult.newSuccessfulResult(combined)); }
                        catch (Throwable failure) { completeExceptionally(failure); }
                    }
                    return;
                }
                for (SearchResult item : page) {
                    boolean calendar = "CalendarEvent".equals(item.getGenericDocument().getSchemaType());
                    if (calendar) calendars++;
                    if (pages == 1 || calendar) combined.add(item);
                }
                if (pages >= 100) { fail(AppSearchResult.RESULT_INTERNAL_ERROR, "Calendar page bound exceeded"); return; }
                if (!finished.get()) search.getNextPage(executor, this);
            } catch (Throwable failure) { fail(AppSearchResult.RESULT_INTERNAL_ERROR, "Calendar page processing failed"); }
        }
        void fail(int code, String message) {
            if (!finished.compareAndSet(false, true)) return;
            handler.removeCallbacks(timeout);
            try {
                invoke(contract.callbackAccept, callback,
                        AppSearchResult.newFailedResult(code, message == null ? "Calendar page read failed" : message));
            } catch (Throwable failure) { completeExceptionally(failure); }
        }
        void completeExceptionally(Throwable failure) {
            try { invoke(contract.futureFail, future, failure); }
            catch (Throwable completionFailure) { error("future completion", completionFailure); }
            error("page completion", failure);
        }
    }
}
