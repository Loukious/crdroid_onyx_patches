"""Run copied production code without invoking Soong or touching a ROM build.

Set ONYX_LOG_FIX_ROM to an isolated source snapshot with the four fixes applied.
Set ONYX_KOTLINC, ONYX_ANDROID_TEST_JAR and ONYX_ROBOLECTRIC_TEST_JAR to existing
host dependencies. ONYX_LOG_FIX_OUT optionally retains compilation/test logs.
The blur and query harnesses model UI/service boundaries; serialization uses
the real Android protobuf implementation under Robolectric.
"""
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("log_fix_source", ROOT / "ci/upstream_fix_state.py")
source_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source_tools)


def method(source, pattern, optional=False):
    code = source_tools.code_only(source)
    match = re.search(pattern, code)
    if not match and optional:
        return ""
    if not match:
        raise AssertionError("production method not found: " + pattern)
    start = code.index("{", match.start())
    return source[match.start():source_tools.block_end(code, start)]


BLUR = r'''
public class BlurHarness {
    static boolean mainThread = true;
    static int failures, passed;
    static class R {
        static class id { static final int backgroundNormal=1, fake_shadow=2; }
        static class drawable { static final int notification_material_bg=1; }
    }
    static class Background {
        int calls, reloads;
        boolean enabled;
        void setCustomBackground(int id) { reloads++; }
        void setBlurBackgroundEnabled(boolean value) {
            if (!mainThread) throw new IllegalStateException("blur requires main thread");
            calls++; enabled=value;
        }
    }
    static class Shadow { int getVisibility() { return 0; } }
    static class Parent {
        protected void onFinishInflate() {}
        protected void onAttachedToWindow() {}
    }
    static class Row extends Parent {
        static final int VISIBLE=0;
        final Background background = new Background();
        Background mBackgroundNormal;
        Shadow mFakeShadow;
        boolean mShadowHidden, attached, blurred;
        @SuppressWarnings("unchecked")
        <T> T findViewById(int id) {
            return (T)(id==R.id.backgroundNormal ? background : new Shadow());
        }
        boolean isAttachedToWindow() { return attached; }
        boolean usesBlurredBackground() { return blurred; }
        void updateBackgroundTint() {}
        void updateOutlineAlpha() {}
        void attach() { attached=true; onAttachedToWindow(); }
@@METHODS@@
    }
    interface Case { void run() throws Exception; }
    static void check(String name, Case body) {
        mainThread=true;
        try { body.run(); passed++; }
        catch (Throwable failure) { failures++; System.out.println("FAIL " + name + ": " + failure); }
        finally { mainThread=true; }
    }
    static void expect(boolean condition) { if (!condition) throw new AssertionError(); }
    public static void main(String[] args) {
        check("background inflation", () -> {
            Row row=new Row(); mainThread=false; row.onFinishInflate();
            expect(row.background.calls==0 && row.background.reloads==1);
        });
        check("unattached initialization", () -> {
            Row row=new Row(); row.onFinishInflate(); expect(row.background.calls==0);
        });
        check("attachment uses latest state", () -> {
            Row row=new Row(); row.onFinishInflate(); row.blurred=true; row.attach();
            expect(row.background.enabled);
        });
        check("attached background reload", () -> {
            Row row=new Row(); row.onFinishInflate(); row.attach(); row.blurred=true;
            row.initBackground(); expect(row.background.enabled && row.background.reloads==2);
        });
        check("reattachment updates blur", () -> {
            Row row=new Row(); row.onFinishInflate(); row.blurred=true; row.attach();
            row.attached=false; row.blurred=false; row.attach(); expect(!row.background.enabled);
        });
        check("attached work keeps thread assertion", () -> {
            Row row=new Row(); row.onFinishInflate(); row.attach(); mainThread=false;
            try { row.initBackground(); throw new AssertionError("thread assertion removed"); }
            catch (IllegalStateException expected) {}
        });
        System.out.println("blur cases: passed="+passed+" failed="+failures);
        if (failures!=0) System.exit(1);
    }
}
'''

WIFI = r'''
object Input {
    var permission=true; var appOp=true; var key=true; var wifi=true
    var failSpecific=false; var failAggregate=false
    var deniedQueries=0
    val queries=mutableListOf<String>()
    fun reset() {
        permission=true; appOp=true; key=true; wifi=true
        failSpecific=false; failAggregate=false; deniedQueries=0; queries.clear()
    }
}
object Manifest { object permission { const val ACCESS_FINE_LOCATION="fine" } }
object PermissionChecker {
    const val PERMISSION_GRANTED=0
    fun checkSelfPermissionForPreflight(context: Context, permission: String): Int =
        if (Input.permission && Input.appOp) 0 else -1
}
object R { object string { const val usage_wifi_default_suffix=1 } }
class Context { fun getString(id: Int)="Wi-Fi" }
data class SubscriptionInfo(val id: Int)
class SubMgr { val activeSubscriptionInfoList: List<SubscriptionInfo>?=listOf(SubscriptionInfo(1)) }
data class Template(val wifiNetworkKeys: Set<String>)
data class Info(val usageLevel: Long, val carrier: String?=null)
class DataUsageController {
    fun getWifiNetworkTemplate(current: Boolean)=Template(
        if (current && Input.key) setOf("network-key") else emptySet())
    private fun usage(template: Template, weekly: Boolean): Info? {
        val specific=template.wifiNetworkKeys.isNotEmpty()
        Input.queries.add(if (specific) "specific" else "aggregate")
        if (specific && (!Input.permission || !Input.appOp)) {
            Input.deniedQueries++; return null
        }
        if ((specific && Input.failSpecific) || (!specific && Input.failAggregate)) return null
        return Info(if (specific) { if (weekly) 222L else 111L }
                    else { if (weekly) 888L else 999L })
    }
    fun getDailyDataUsageInfo(t: Template)=usage(t,false)
    fun getWeeklyDataUsageInfo(t: Template)=usage(t,true)
    fun getWifiDailyDataUsageInfo(current: Boolean)=usage(getWifiNetworkTemplate(current),false)
    fun getWifiWeeklyDataUsageInfo(current: Boolean)=usage(getWifiNetworkTemplate(current),true)
    fun setSubscriptionId(id: Int) {}
    fun getDailyDataUsageInfo()=Info(42L,"Carrier")
    fun getWeeklyDataUsageInfo()=Info(84L,"Carrier")
}
object Log { fun w(tag: String, message: String, e: RuntimeException) {} }
const val TAG="query-test"
class Subject {
    val context=Context(); val subMgr=SubMgr(); val duc=DataUsageController(); var subId=1
    fun resolveSubId(subs: List<SubscriptionInfo>) {}
    fun isWifiConnected()=Input.wifi
    fun ssidWithTruncation()="Current"
    fun fallbackCarrierName(subs: List<SubscriptionInfo>, id: Int)="Carrier"
    fun formatDataUsage(bytes: Long, suffix: String, weekly: Boolean)=
        "$bytes|$suffix|${if (weekly) "W" else "D"}"
@@METHODS@@
}
var passed=0; var failed=0
fun check(name: String, weekly: Boolean, expected: String?, calls: List<String>,
          configure: () -> Unit = {}) {
    Input.reset(); configure()
    try {
        val actual=Subject().query(weekly)
        check(actual==expected) { "expected=$expected actual=$actual" }
        check(Input.queries==calls) { "queries=${Input.queries}" }
        check(Input.deniedQueries==0) { "repeated permission-denied query" }
        passed++
    } catch (failure: Throwable) { failed++; println("FAIL $name: $failure") }
}
fun main() {
    check("daily current network",false,"111|Current|D",listOf("specific"))
    check("weekly current network",true,"222|Current|W",listOf("specific"))
    check("denied permission",false,"999|Wi-Fi|D",listOf("aggregate")) { Input.permission=false }
    check("denied app-op",true,"888|Wi-Fi|W",listOf("aggregate")) { Input.appOp=false }
    check("missing network key",false,"999|Wi-Fi|D",listOf("aggregate")) { Input.key=false }
    check("failed keyed query",false,"999|Wi-Fi|D",listOf("specific","aggregate")) {
        Input.failSpecific=true
    }
    check("both queries failed",true,null,listOf("specific","aggregate")) {
        Input.failSpecific=true; Input.failAggregate=true
    }
    check("failed aggregate is not repeated",false,null,listOf("aggregate")) {
        Input.key=false; Input.failAggregate=true
    }
    check("mobile query preserved",false,"42|Carrier|D",emptyList()) { Input.wifi=false }
    println("Wi-Fi cases: passed=$passed failed=$failed")
    if (failed!=0) kotlin.system.exitProcess(1)
}
'''

HISTORY = r'''
package com.android.server.notification;
import static org.junit.Assert.*;
import android.app.NotificationHistory;
import android.app.Application;
import android.app.NotificationHistory.HistoricalNotification;
import android.graphics.drawable.Icon;
import android.util.proto.ProtoInputStream;
import android.util.proto.ProtoOutputStream;
import java.io.*;
import java.util.*;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.junit.runners.model.InitializationError;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

@RunWith(HistoryHarnessTest.BareRunner.class)
@Config(manifest=Config.NONE, sdk=35, application=Application.class)
public class HistoryHarnessTest {
    public static class BareRunner extends RobolectricTestRunner {
        public BareRunner(Class<?> testClass) throws InitializationError { super(testClass); }
        @Override protected Properties getBuildSystemApiProperties() {
            // A reused AOSP test dependency may contain an unrelated APK's
            // build-system metadata. These serializer tests need no APK.
            return null;
        }
    }
    private HistoricalNotification notification(String channel, long when) {
        return new HistoricalNotification.Builder().setPackage("shared.package")
            .setChannelName("Channel").setChannelId(channel).setConversationId("conversation")
            .setUid(10000).setUserId(0).setPostedTimeMs(when).setTitle("title").setText("text")
            .setIcon(Icon.createWithResource("shared.package",1)).build();
    }
    private byte[] write(NotificationHistory history) {
        ByteArrayOutputStream out=new ByteArrayOutputStream();
        NotificationHistoryProtoHelper.write(out,history,1); return out.toByteArray();
    }
    private List<String> pool(byte[] data) throws Exception {
        ProtoInputStream in=new ProtoInputStream(data); List<String> pool=new ArrayList<>();
        int size=0; // Zero-valued protobuf fields may be omitted.
        while (in.nextField()!=ProtoInputStream.NO_MORE_FIELDS) {
            if (in.getFieldNumber()!=(int)NotificationHistoryProto.STRING_POOL) continue;
            long token=in.start(NotificationHistoryProto.STRING_POOL);
            while (in.nextField()!=ProtoInputStream.NO_MORE_FIELDS) {
                if (in.getFieldNumber()==(int)NotificationHistoryProto.StringPool.STRINGS)
                    pool.add(in.readString(NotificationHistoryProto.StringPool.STRINGS));
                else if (in.getFieldNumber()==(int)NotificationHistoryProto.StringPool.SIZE)
                    size=in.readInt(NotificationHistoryProto.StringPool.SIZE);
            }
            in.end(token);
        }
        assertEquals("declared string pool size",pool.size(),size); return pool;
    }
    @Test public void freshEntriesUseDeduplicatedPool() throws Exception {
        NotificationHistory h=new NotificationHistory();
        h.addNewNotificationToWrite(notification("one",1));
        h.addNewNotificationToWrite(notification("two",2));
        assertEquals("fresh string pool",Set.of("shared.package","Channel","conversation","one","two"),
            new HashSet<>(pool(write(h))));
        assertEquals(5,pool(write(h)).size());
    }
    @Test public void stalePoolIsReplacedBeforeSaving() throws Exception {
        NotificationHistory h=new NotificationHistory();
        h.addPooledStrings(List.of("stale"));
        h.addNewNotificationToWrite(notification("one",1));
        assertEquals("stale string pool",Set.of("shared.package","Channel","conversation","one"),
            new HashSet<>(pool(write(h))));
        assertEquals(Collections.emptyList(),pool(write(new NotificationHistory())));
    }
    @Test public void fieldsAndOrderRoundTrip() throws Exception {
        NotificationHistory h=new NotificationHistory();
        h.addNewNotificationToWrite(notification("one",1));
        h.addNewNotificationToWrite(notification("two",2));
        NotificationHistory read=new NotificationHistory();
        NotificationHistoryProtoHelper.read(new ByteArrayInputStream(write(h)),read,
            new NotificationHistoryFilter.Builder().build());
        assertEquals(2,read.getHistoryCount());
        List<HistoricalNotification> rows=read.getNotificationsToWrite();
        assertEquals("two",rows.get(0).getChannelId());
        assertEquals("one",rows.get(1).getChannelId());
        for (HistoricalNotification n: rows) {
            assertEquals("shared.package",n.getPackage()); assertEquals("Channel",n.getChannelName());
            assertEquals("conversation",n.getConversationId()); assertEquals("title",n.getTitle());
            assertEquals("text",n.getText()); assertEquals(10000,n.getUid());
            assertEquals(Icon.TYPE_RESOURCE,n.getIcon().getType()); assertEquals(1,n.getIcon().getResId());
        }
    }
    @Test public void legacyInlineStringsRemainReadable() throws Exception {
        ByteArrayOutputStream out=new ByteArrayOutputStream();
        ProtoOutputStream p=new ProtoOutputStream(out);
        p.write(NotificationHistoryProto.MAJOR_VERSION,1);
        long pool=p.start(NotificationHistoryProto.STRING_POOL);
        p.write(NotificationHistoryProto.StringPool.SIZE,0); p.end(pool);
        long row=p.start(NotificationHistoryProto.NOTIFICATION);
        p.write(NotificationHistoryProto.Notification.PACKAGE,"legacy.package");
        p.write(NotificationHistoryProto.Notification.CHANNEL_ID,"legacy.channel");
        p.write(NotificationHistoryProto.Notification.CHANNEL_NAME,"Legacy");
        p.write(NotificationHistoryProto.Notification.CONVERSATION_ID,"legacy.conversation");
        p.end(row); p.flush();
        NotificationHistory read=new NotificationHistory();
        NotificationHistoryProtoHelper.read(new ByteArrayInputStream(out.toByteArray()),read,
            new NotificationHistoryFilter.Builder().build());
        assertEquals(1,read.getHistoryCount());
        HistoricalNotification n=read.getNotificationsToWrite().get(0);
        assertEquals("legacy.package",n.getPackage()); assertEquals("legacy.channel",n.getChannelId());
        assertEquals("Legacy",n.getChannelName()); assertEquals("legacy.conversation",n.getConversationId());
    }
}
'''


@unittest.skipUnless(os.environ.get("ONYX_LOG_FIX_ROM"), "requires an isolated ROM snapshot")
class LogFixBehavior(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom = Path(os.environ["ONYX_LOG_FIX_ROM"])
        cls.base = cls.rom / "frameworks/base"
        if os.environ.get("ONYX_LOG_FIX_OUT"):
            cls.work = Path(os.environ["ONYX_LOG_FIX_OUT"])
            cls.work.mkdir(parents=True, exist_ok=True)
        else:
            cls.temp = tempfile.TemporaryDirectory(prefix="onyx-log-fix-")
            cls.addClassCleanup(cls.temp.cleanup)
            cls.work = Path(cls.temp.name)

    def versions(self, relative):
        yield "baseline", subprocess.check_output(
            ["git", "-C", str(self.base), "show", "HEAD:" + relative], text=True)
        yield "patched", (self.base / relative).read_text()

    def run_logged(self, command, work, name, timeout=60):
        # Some AOSP test-runner diagnostics dump the environment. Host tests
        # need no connector credentials or unrelated session configuration.
        env = {name: os.environ[name] for name in ("PATH", "JAVA_HOME", "LANG", "LC_ALL")
               if name in os.environ}
        result = subprocess.run([str(p) for p in command], cwd=work,
                                capture_output=True, text=True, timeout=timeout, env=env)
        (work / (name + ".log")).write_text(result.stdout + result.stderr)
        return result

    def test_blur_lifecycle(self):
        path = "packages/SystemUI/src/com/android/systemui/statusbar/notification/row/ActivatableNotificationView.java"
        for version, source in self.versions(path):
            with self.subTest(version=version):
                methods = [method(source, r"protected void onFinishInflate\(\)"),
                           method(source, r"protected void initBackground\(\)"),
                           method(source, r"protected void onAttachedToWindow\(\)", optional=True)]
                work = self.work / ("blur-" + version); work.mkdir(exist_ok=True)
                (work / "BlurHarness.java").write_text(BLUR.replace("@@METHODS@@", "\n".join(methods)))
                compiled = self.run_logged(["javac", "BlurHarness.java"], work, "compile")
                self.assertEqual(compiled.returncode, 0, compiled.stderr)
                result = self.run_logged(["java", "-Xmx128m", "BlurHarness"], work, "run")
                if version == "baseline":
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("FAIL background inflation", result.stdout)
                else:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("passed=6 failed=0", result.stdout)

    def test_wifi_queries_and_labels(self):
        path = "packages/SystemUI/src/com/android/systemui/development/ui/compose/BuildNumber.kt"
        for version, source in self.versions(path):
            with self.subTest(version=version):
                methods = [method(source, r"fun query\(weekly: Boolean\): String\?"),
                           method(source, r"private fun queryWifiUsage\(weekly: Boolean\): String\?", optional=True)]
                work = self.work / ("wifi-" + version); work.mkdir(exist_ok=True)
                (work / "WifiHarness.kt").write_text(WIFI.replace("@@METHODS@@", "\n".join(methods)))
                compiled = self.run_logged([os.environ["ONYX_KOTLINC"], "-J-Xmx384m",
                    "WifiHarness.kt", "-include-runtime", "-d", "wifi.jar"], work, "compile")
                self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
                result = self.run_logged(["java", "-Xmx128m", "-jar", "wifi.jar"], work, "run")
                if version == "baseline":
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("FAIL denied permission", result.stdout)
                    self.assertIn("FAIL missing network key", result.stdout)
                else:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("passed=9 failed=0", result.stdout)

    def test_systemui_declares_foreground_location(self):
        namespace = "{http://schemas.android.com/apk/res/android}"
        manifest = ET.parse(self.base / "packages/SystemUI/AndroidManifest.xml").getroot()
        permissions = [row.get(namespace + "name") for row in manifest.findall("uses-permission")]
        for permission in ("ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION"):
            self.assertEqual(permissions.count("android.permission." + permission), 1)
        self.assertNotIn("android.permission.ACCESS_BACKGROUND_LOCATION", permissions)
        # Persistent platform-signed privileged apps use the existing default
        # grant policy; this patch does not add a NetworkStats permission bypass.
        self.assertEqual(manifest.find("application").get(namespace + "persistent"), "true")

    def test_notification_history_serialization(self):
        path = "services/core/java/com/android/server/notification/NotificationHistoryProtoHelper.java"
        android = Path(os.environ["ONYX_ANDROID_TEST_JAR"])
        runner = Path(os.environ["ONYX_ROBOLECTRIC_TEST_JAR"])
        dependencies = os.pathsep.join([str(android), str(runner)])
        for version, source in self.versions(path):
            with self.subTest(version=version):
                work = self.work / ("history-" + version); work.mkdir(exist_ok=True)
                # Use a distinct class name so Robolectric cannot substitute
                # the SDK jar's older copy of this framework implementation.
                host_name = "HostNotificationHistoryProtoHelper"
                (work / (host_name + ".java")).write_text(
                    source.replace("NotificationHistoryProtoHelper", host_name))
                (work / "HistoryHarnessTest.java").write_text(
                    HISTORY.replace("NotificationHistoryProtoHelper", host_name))
                compiled = self.run_logged(["javac", "-cp", dependencies, "-d", "classes",
                    host_name + ".java", "HistoryHarnessTest.java"], work, "compile")
                self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
                result = self.run_logged(["java", "-Xmx512m", "-Drobolectric.offline=true",
                    "-Drobolectric.usePreinstrumentedJars=false",
                    "-Drobolectric.dependency.dir=" + str(android.parent),
                    "-cp", os.pathsep.join([str(work / "classes"), str(runner), str(android)]),
                    "org.junit.runner.JUnitCore", "com.android.server.notification.HistoryHarnessTest"],
                    work, "run")
                if version == "baseline":
                    self.assertNotEqual(result.returncode, 0)
                    self.assertTrue("fresh string pool" in result.stdout,
                                    "baseline did not reach the regression; see " + str(work / "run.log"))
                    self.assertIn("Tests run: 4", result.stdout)
                else:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("OK (4 tests)", result.stdout)


if __name__ == "__main__":
    unittest.main()
