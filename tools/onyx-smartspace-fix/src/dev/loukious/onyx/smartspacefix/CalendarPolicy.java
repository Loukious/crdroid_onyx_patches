package dev.loukious.onyx.smartspacefix;

import java.util.Collection;
import java.util.Objects;

/** Selects a timed occurrence during its upcoming and in-progress display window. */
public final class CalendarPolicy {
    private static final long MINUTE_MILLIS = 60_000L;
    private static final long CLOCK_RECHECK_MILLIS = 6L * 60 * 60 * 1000;

    private CalendarPolicy() {}

    public static class Candidate {
        public final String id;
        public final long start;
        public final long end;
        public final long windowStart;
        public final long windowEnd;

        public Candidate(String id, long start, long end, long windowStart, long windowEnd) {
            this.id = id;
            this.start = start;
            this.end = end;
            this.windowStart = windowStart;
            this.windowEnd = windowEnd;
        }
    }

    public static class Decision {
        public final Candidate best;
        public final Long nextBoundary;

        public Decision(Candidate best, Long nextBoundary) {
            this.best = best;
            this.nextBoundary = nextBoundary;
        }
    }

    public static Decision choose(Collection<? extends Candidate> candidates, long now) {
        Objects.requireNonNull(candidates, "candidates");
        Candidate best = null;
        Long nextBoundary = null;
        for (Candidate item : candidates) {
            if (item == null || item.id == null) continue;
            // The bridge extends timed-event metadata to the occurrence end. Retain its
            // earlier expiry if present, but never keep a card beyond the event itself.
            long expiry = Math.min(item.end, item.windowEnd);
            if (item.end < item.start || item.windowStart > item.start
                    || item.windowStart >= expiry || now >= expiry) continue;
            long boundary = now < item.windowStart ? item.windowStart
                    : now < item.start ? Math.min(item.start, expiry) : expiry;
            if (nextBoundary == null || boundary < nextBoundary) nextBoundary = boundary;
            if (now < item.windowStart) continue;
            // Earlier starts also put in-progress events before upcoming events, so a
            // visible meeting remains selected until it ends instead of being displaced.
            if (best == null || item.start < best.start
                    || (item.start == best.start && item.id.compareTo(best.id) < 0)) {
                best = item;
            }
        }
        if (best != null && now < best.start) {
            // Refresh only the displayed countdown, at the next ceiling-minute decrement.
            // Align to the event's own seconds rather than the wall clock's minute boundary.
            long remainder = Long.remainderUnsigned(best.start - now, MINUTE_MILLIS);
            long boundary = now + (remainder == 0 ? MINUTE_MILLIS : remainder);
            if (nextBoundary == null || boundary < nextBoundary) nextBoundary = boundary;
        }
        return new Decision(best, nextBoundary);
    }

    /** Upcoming countdown rounds up; the start and all active times are represented by zero. */
    public static long minutesUntilStart(long start, long now) {
        if (now >= start) return 0;
        // Signed timestamps can span more than Long.MAX_VALUE, while the minute count cannot.
        long remaining = start - now;
        long minutes = Long.divideUnsigned(remaining, MINUTE_MILLIS);
        return minutes + (Long.remainderUnsigned(remaining, MINUTE_MILLIS) == 0 ? 0 : 1);
    }

    /** Uses a bounded wall-clock recheck even when the next window is far away. */
    public static long delay(long now, long boundary) {
        if (boundary <= now) return 1;
        long remaining = boundary - now;
        // A positive interval can overflow subtraction only when it exceeds the cap.
        if (remaining <= 0 || remaining > CLOCK_RECHECK_MILLIS) {
            return CLOCK_RECHECK_MILLIS;
        }
        return remaining;
    }
}
