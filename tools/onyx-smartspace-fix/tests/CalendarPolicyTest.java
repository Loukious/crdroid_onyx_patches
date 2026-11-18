package dev.loukious.onyx.smartspacefix;

import java.time.Instant;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

import dev.loukious.onyx.smartspacefix.CalendarPolicy.Candidate;
import dev.loukious.onyx.smartspacefix.CalendarPolicy.Decision;

/** Host-only regression tests; run with javac/java and no external test framework. */
public final class CalendarPolicyTest {
    private static final long MINUTE = 60_000L;
    private static final long HOUR = 60 * MINUTE;
    private static int checks;

    public static void main(String[] args) {
        check("distant events remain hidden", CalendarPolicyTest::distantEvents);
        check("next-day event appears across midnight", CalendarPolicyTest::acrossMidnight);
        check("window opening inclusive, expiry exclusive", CalendarPolicyTest::exactBoundaries);
        check("meeting stays visible from countdown through its end", CalendarPolicyTest::meetingTimeline);
        check("countdown rounds up and becomes zero at the start", CalendarPolicyTest::countdownMinutes);
        check("countdown refresh follows the event's seconds", CalendarPolicyTest::countdownBoundaries);
        check("only the selected upcoming card needs minute refreshes", CalendarPolicyTest::selectedCountdownOnly);
        check("earliest eligible event and stable ID tie break", CalendarPolicyTest::ranking);
        check("active meeting stays ahead of an upcoming meeting", CalendarPolicyTest::activeBeforeUpcoming);
        check("ineligible early event cannot hide an eligible later one", CalendarPolicyTest::filterBeforeRank);
        check("retained events promote and eventually expire", CalendarPolicyTest::promotion);
        check("metadata expiry never extends occurrence lifetime", CalendarPolicyTest::metadataExpiry);
        check("empty and malformed windows have no boundary", CalendarPolicyTest::malformedWindows);
        check("backward and forward clock changes recompute eligibility", CalendarPolicyTest::clockChanges);
        check("timer delays are bounded, including overflow", CalendarPolicyTest::timerDelays);
        check("candidate subclasses preserve the selected object", CalendarPolicyTest::subclassIdentity);
        check("events without a usable end retain their upcoming window", CalendarPolicyTest::pointOccurrence);
        System.out.println(checks + " calendar policy checks passed.");
    }

    private static void distantEvents() {
        long now = time("2026-11-13T08:00:00Z");
        Candidate today = occurrence("today", time("2026-11-13T14:00:00Z"));
        Candidate tomorrow = occurrence("tomorrow", time("2026-11-14T07:45:00Z"));
        decision(CalendarPolicy.choose(Arrays.asList(tomorrow, today), now), null, today.windowStart);
    }

    private static void pointOccurrence() {
        long start = time("2026-11-13T14:00:00Z");
        Candidate point = new Candidate("point", start, start, start - 30 * MINUTE, start);
        List<Candidate> items = Collections.singletonList(point);
        decision(CalendarPolicy.choose(items, start - MINUTE), point.id, start);
        decision(CalendarPolicy.choose(items, start), null, null);
    }

    private static void acrossMidnight() {
        Candidate item = occurrence("after-midnight", time("2026-11-14T00:05:00Z"));
        decision(CalendarPolicy.choose(Collections.singletonList(item), time("2026-11-13T23:50:00Z")),
                "after-midnight", time("2026-11-13T23:51:00Z"));
    }

    private static void exactBoundaries() {
        Candidate item = occurrence("boundary", time("2026-11-13T14:00:00Z"));
        List<Candidate> items = Collections.singletonList(item);
        decision(CalendarPolicy.choose(items, item.windowStart - 1), null, item.windowStart);
        decision(CalendarPolicy.choose(items, item.windowStart), item.id, item.windowStart + MINUTE);
        decision(CalendarPolicy.choose(items, item.start - 1), item.id, item.start);
        decision(CalendarPolicy.choose(items, item.start), item.id, item.end);
        decision(CalendarPolicy.choose(items, item.start + 1), item.id, item.end);
        decision(CalendarPolicy.choose(items, item.end - 1), item.id, item.end);
        decision(CalendarPolicy.choose(items, item.end), null, null);
        decision(CalendarPolicy.choose(items, item.end + 1), null, null);
    }

    private static void meetingTimeline() {
        Candidate meeting = occurrence("meeting", time("2026-11-13T14:00:00Z"));
        List<Candidate> items = Collections.singletonList(meeting);
        decision(CalendarPolicy.choose(items, time("2026-11-13T13:29:59Z")), null, meeting.windowStart);
        decision(CalendarPolicy.choose(items, time("2026-11-13T13:30:00Z")), meeting.id,
                time("2026-11-13T13:31:00Z"));
        decision(CalendarPolicy.choose(items, time("2026-11-13T13:59:59Z")), meeting.id, meeting.start);
        decision(CalendarPolicy.choose(items, time("2026-11-13T14:00:00Z")), meeting.id, meeting.end);
        decision(CalendarPolicy.choose(items, time("2026-11-13T14:59:59Z")), meeting.id, meeting.end);
        decision(CalendarPolicy.choose(items, time("2026-11-13T15:00:00Z")), null, null);
    }

    private static void countdownMinutes() {
        long start = time("2026-11-13T14:00:17Z");
        equal(30, CalendarPolicy.minutesUntilStart(start, start - 30 * MINUTE), "thirty minutes");
        equal(15, CalendarPolicy.minutesUntilStart(start, start - 15 * MINUTE), "fifteen minutes");
        equal(5, CalendarPolicy.minutesUntilStart(start, start - 5 * MINUTE), "five minutes");
        equal(1, CalendarPolicy.minutesUntilStart(start, start - MINUTE), "exact one minute");
        equal(2, CalendarPolicy.minutesUntilStart(start, start - MINUTE - 1), "one minute plus a millisecond");
        equal(1, CalendarPolicy.minutesUntilStart(start, start - 1_000), "one second");
        equal(1, CalendarPolicy.minutesUntilStart(start, start - 1), "last millisecond");
        equal(0, CalendarPolicy.minutesUntilStart(start, start), "start becomes now");
        equal(0, CalendarPolicy.minutesUntilStart(start, start + MINUTE), "active remains now");
        equal(307445734561826L, CalendarPolicy.minutesUntilStart(Long.MAX_VALUE, Long.MIN_VALUE),
                "wide timestamp interval does not overflow");
        equal(1, CalendarPolicy.minutesUntilStart(Long.MAX_VALUE, Long.MAX_VALUE - 1), "upper limit");
    }

    private static void countdownBoundaries() {
        Candidate item = occurrence("seconds", time("2026-11-13T14:00:17Z"));
        List<Candidate> items = Collections.singletonList(item);
        long nextMinute = time("2026-11-13T13:31:17Z");
        decision(CalendarPolicy.choose(items, item.windowStart - 1), null, item.windowStart);
        decision(CalendarPolicy.choose(items, item.windowStart), item.id, nextMinute);
        decision(CalendarPolicy.choose(items, item.windowStart + 1), item.id, nextMinute);
        decision(CalendarPolicy.choose(items, nextMinute - 1), item.id, nextMinute);
        decision(CalendarPolicy.choose(items, nextMinute), item.id, nextMinute + MINUTE);
        decision(CalendarPolicy.choose(items, item.start - MINUTE), item.id, item.start);
        decision(CalendarPolicy.choose(items, item.start - 1_000), item.id, item.start);
        decision(CalendarPolicy.choose(items, item.start), item.id, item.end);
        decision(CalendarPolicy.choose(items, item.start + MINUTE), item.id, item.end);

        Candidate shortWindow = new Candidate("earlier-expiry", item.start, item.end,
                item.windowStart, item.start - 15_000);
        decision(CalendarPolicy.choose(Collections.singletonList(shortWindow), item.start - 30_000),
                shortWindow.id, shortWindow.windowEnd);
    }

    private static void selectedCountdownOnly() {
        Candidate first = occurrence("selected", time("2026-11-13T14:00:37Z"));
        Candidate second = occurrence("other", time("2026-11-13T14:05:03Z"));
        // Both windows are open, but the other title's countdown would change earlier.
        decision(CalendarPolicy.choose(Arrays.asList(second, first), time("2026-11-13T13:45:00Z")),
                first.id, time("2026-11-13T13:45:37Z"));
    }

    private static void ranking() {
        long firstStart = time("2026-11-13T14:00:00Z");
        Candidate later = occurrence("0-later", firstStart + 10 * MINUTE);
        Candidate a = occurrence("a", firstStart);
        Candidate z = occurrence("z", firstStart);
        long now = firstStart - 10 * MINUTE;
        decision(CalendarPolicy.choose(Arrays.asList(later, z, a), now), "a", now + MINUTE);
        decision(CalendarPolicy.choose(Arrays.asList(a, later, z), now), "a", now + MINUTE);
    }

    private static void filterBeforeRank() {
        long now = time("2026-11-13T12:00:00Z");
        Candidate hidden = occurrence("hidden", now + HOUR);
        Candidate eligible = new Candidate("eligible", now + 2 * HOUR, now + 3 * HOUR,
                now - MINUTE, now + 3 * HOUR);
        decision(CalendarPolicy.choose(Arrays.asList(hidden, eligible), now), eligible.id, now + MINUTE);
    }

    private static void promotion() {
        Candidate first = occurrence("first", time("2026-11-13T14:00:00Z"));
        Candidate second = occurrence("second", first.start + 20 * MINUTE);
        List<Candidate> items = Arrays.asList(second, first);
        decision(CalendarPolicy.choose(items, first.windowStart - 1), null, first.windowStart);
        decision(CalendarPolicy.choose(items, first.windowStart), first.id, first.windowStart + MINUTE);
        decision(CalendarPolicy.choose(items, second.windowStart), first.id, second.windowStart + MINUTE);
        decision(CalendarPolicy.choose(items, first.start), first.id, second.start);
        decision(CalendarPolicy.choose(items, second.start), first.id, first.end);
        decision(CalendarPolicy.choose(items, first.end), second.id, second.end);
        decision(CalendarPolicy.choose(items, second.end), null, null);
    }

    private static void activeBeforeUpcoming() {
        Candidate active = occurrence("z-active", time("2026-11-13T14:00:00Z"));
        Candidate upcoming = occurrence("a-upcoming", active.end);
        List<Candidate> items = Arrays.asList(upcoming, active);
        decision(CalendarPolicy.choose(items, active.start + 40 * MINUTE), active.id, active.end);
        decision(CalendarPolicy.choose(items, active.end - 1), active.id, active.end);
        decision(CalendarPolicy.choose(items, active.end), upcoming.id, upcoming.end);
    }

    private static void metadataExpiry() {
        long now = time("2026-11-13T12:00:00Z");
        Candidate shortWindow = new Candidate("short", now + HOUR, now + 2 * HOUR,
                now, now + MINUTE);
        decision(CalendarPolicy.choose(Collections.singletonList(shortWindow), now), shortWindow.id, now + MINUTE);
        decision(CalendarPolicy.choose(Collections.singletonList(shortWindow), now + MINUTE), null, null);
        Candidate extended = new Candidate("extended", now + MINUTE, now + 2 * MINUTE,
                now, now + HOUR);
        decision(CalendarPolicy.choose(Collections.singletonList(extended), now), extended.id, extended.start);
        decision(CalendarPolicy.choose(Collections.singletonList(extended), extended.start), extended.id, extended.end);
        decision(CalendarPolicy.choose(Collections.singletonList(extended), extended.end), null, null);
    }

    private static void malformedWindows() {
        decision(CalendarPolicy.choose(Collections.emptyList(), 0), null, null);
        List<Candidate> items = Arrays.asList(
                new Candidate("negative-duration", 100, 90, 0, 100),
                new Candidate("empty-window", 100, 200, 100, 100),
                new Candidate("inverted-window", 100, 200, 90, 80),
                new Candidate("opens-after-start", 100, 200, 110, 200),
                new Candidate(null, 100, 200, 0, 200), null);
        decision(CalendarPolicy.choose(items, 0), null, null);
        Candidate valid = occurrence("valid", time("2026-11-13T14:00:00Z"));
        decision(CalendarPolicy.choose(Arrays.asList(items.get(0), valid), valid.windowStart),
                valid.id, valid.windowStart + MINUTE);
    }

    private static void clockChanges() {
        long now = time("2026-11-13T12:00:00Z");
        Candidate item = occurrence("clock", now + 10 * MINUTE);
        List<Candidate> items = Collections.singletonList(item);
        decision(CalendarPolicy.choose(items, now), item.id, now + MINUTE);
        decision(CalendarPolicy.choose(items, now - HOUR), null, item.windowStart);
        decision(CalendarPolicy.choose(items, item.windowStart), item.id, item.windowStart + MINUTE);
        decision(CalendarPolicy.choose(items, item.end + 1), null, null);
        decision(CalendarPolicy.choose(items, now), item.id, now + MINUTE);
    }

    private static void timerDelays() {
        equal(6 * HOUR, CalendarPolicy.delay(0, 24 * HOUR), "long wait cap");
        equal(6 * HOUR, CalendarPolicy.delay(0, 6 * HOUR), "exact cap");
        equal(MINUTE, CalendarPolicy.delay(0, MINUTE), "near boundary");
        equal(1, CalendarPolicy.delay(100, 101), "one millisecond boundary");
        equal(1, CalendarPolicy.delay(100, 100), "due boundary");
        equal(1, CalendarPolicy.delay(100, 0), "past boundary");
        equal(6 * HOUR, CalendarPolicy.delay(Long.MIN_VALUE, Long.MAX_VALUE), "overflow cap");
        equal(1, CalendarPolicy.delay(Long.MAX_VALUE - 1, Long.MAX_VALUE), "upper limit");
    }

    private static void subclassIdentity() {
        class Captured extends Candidate {
            Captured() { super("captured", 100, 200, 0, 200); }
        }
        Captured item = new Captured();
        Decision result = CalendarPolicy.choose(Collections.singletonList(item), 50);
        if (result.best != item) throw new AssertionError("selection must preserve captured object identity");
    }

    private static Candidate occurrence(String id, long start) {
        return new Candidate(id, start, start + HOUR, start - 30 * MINUTE, start + HOUR);
    }

    private static long time(String value) {
        return Instant.parse(value).toEpochMilli();
    }

    private static void decision(Decision actual, String expectedId, Long expectedBoundary) {
        String actualId = actual.best == null ? null : actual.best.id;
        if (!java.util.Objects.equals(expectedId, actualId)) {
            throw new AssertionError("selected ID: expected " + expectedId + ", got " + actualId);
        }
        if (!java.util.Objects.equals(expectedBoundary, actual.nextBoundary)) {
            throw new AssertionError("boundary: expected " + expectedBoundary + ", got " + actual.nextBoundary);
        }
    }

    private static void equal(long expected, long actual, String label) {
        if (expected != actual) throw new AssertionError(label + ": expected " + expected + ", got " + actual);
    }

    private static void check(String label, Runnable test) {
        test.run();
        checks++;
        System.out.println("PASS " + label);
    }
}
