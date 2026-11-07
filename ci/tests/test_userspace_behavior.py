"""Compile affected production methods in isolated host harnesses.

Set ONYX_USERSPACE_TEST_ROM to a patched checkout and ONYX_ANDROID_TEST_JAR
to an android-all test jar. No source checkout or Android build output is written.
The Binder and process interfaces are modeled; this is not a device test.
"""
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("behavior_guard", ROOT / "ci/upstream_fix_state.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

JAVA = r'''
import java.util.Set;
import org.json.JSONArray;
import org.json.JSONObject;

public class TrickyStorePermissionHarness {
    static int callerUid, expectedUid, foregroundUser, passed, failed;
    static boolean userFailure, packageFailure;
    static String[] packages;
    static String targets;
    Context mContext = new Context();

    static class Binder {
        static int getCallingUid() { return callerUid; }
        static long clearCallingIdentity() { int saved = callerUid; callerUid = 1000; return saved; }
        static void restoreCallingIdentity(long saved) { callerUid = (int) saved; }
    }
    static class ActivityManager {
        static int getCurrentUser() {
            if (callerUid != 1000 && callerUid != 0) throw new SecurityException("cross-user query");
            if (userFailure) throw new IllegalStateException("user lookup failed");
            return foregroundUser;
        }
    }
    static class UserHandle {
        static final int USER_SYSTEM = 0;
        static int getUserId(int uid) { return uid / 100000; }
    }
    static class TrickyStoreService {
        static final Set<String> XPOSED_PACKAGES = Set.of("org.lsposed.manager");
    }
    static class Settings {
        static class Secure { static final String SPOOF_TRICKYSTORE_TARGET = "targets"; }
    }
    static class Context {
        PackageManager getPackageManager() { return new PackageManager(); }
    }
    static class PackageManager {
        String[] getPackagesForUid(int uid) {
            if (callerUid != expectedUid || uid != expectedUid)
                throw new AssertionError("package authorization lost the app identity");
            if (packageFailure) throw new IllegalStateException("package lookup failed");
            return packages;
        }
    }
    String getCached(String key) {
        if (callerUid != expectedUid) throw new AssertionError("cache read lost the app identity");
        return targets;
    }

@@METHOD@@

    static void check(String name, int uid, int foreground, String[] pkgs, String target,
                      boolean expected) {
        callerUid = expectedUid = uid;
        foregroundUser = foreground;
        packages = pkgs;
        targets = target;
        userFailure = packageFailure = false;
        try {
            boolean allowed = new TrickyStorePermissionHarness().canReadTrickyStoreKeybox();
            if (allowed != expected || callerUid != uid) throw new AssertionError("wrong authorization/identity");
            passed++;
        } catch (Throwable failure) {
            failed++;
            System.out.println("FAIL " + name + ": " + failure);
        }
    }
    static void checkFailureRestoresIdentity(boolean failUser) {
        callerUid = expectedUid = 10417;
        foregroundUser = 0;
        packages = new String[]{"allowed.pkg"};
        targets = "allowed.pkg";
        userFailure = failUser;
        packageFailure = !failUser;
        try {
            new TrickyStorePermissionHarness().canReadTrickyStoreKeybox();
            throw new AssertionError("lookup failure did not propagate");
        } catch (IllegalStateException expected) {
            if (callerUid == expectedUid) passed++;
            else { failed++; System.out.println("FAIL exception leaked system identity"); }
        } catch (Throwable failure) {
            failed++; System.out.println("FAIL exception path: " + failure);
        }
    }
    public static void main(String[] args) {
        String[] allowed = {"allowed.pkg"};
        check("owner JSON", 10417, 0, allowed, "[{\"package\":\"allowed.pkg\"}]", true);
        check("owner while another user foreground", 10417, 10, allowed, "allowed.pkg", true);
        check("foreground secondary user", 1010417, 10, allowed, "allowed.pkg", true);
        check("background secondary user", 1110417, 10, allowed, "allowed.pkg", false);
        check("untargeted", 10417, 0, allowed, "different.pkg", false);
        check("no target configuration", 10417, 0, allowed, null, false);
        check("no packages for UID", 10417, 0, null, "allowed.pkg", false);
        check("JSON SKIP", 10417, 0, allowed, "[{\"package\":\"allowed.pkg\",\"mode\":\"SKIP\"}]", false);
        check("legacy SKIP", 10417, 0, allowed, "allowed.pkg-", false);
        check("legacy ! target", 10417, 0, allowed, "allowed.pkg!", true);
        check("legacy ? target", 10417, 0, allowed, "allowed.pkg?", true);
        check("malformed JSON", 10417, 0, allowed, "[", false);
        check("shared UID Xposed exclusion", 10417, 0,
              new String[]{"allowed.pkg", "org.lsposed.manager"}, "allowed.pkg", false);
        check("shared UID SKIP exclusion", 10417, 0, new String[]{"allowed.pkg", "skip.pkg"},
              "[{\"package\":\"allowed.pkg\"},{\"package\":\"skip.pkg\",\"mode\":\"SKIP\"}]", false);
        check("system caller", 1000, 10, null, null, true);
        check("root caller", 0, 10, null, null, true);
        checkFailureRestoresIdentity(true);
        checkFailureRestoresIdentity(false);
        System.out.println("authorization cases: passed=" + passed + " failed=" + failed);
        if (failed != 0) System.exit(1);
    }
}
'''

CPP = r'''
#include <cstring>
#include <string>
#include <iostream>
#include <fcntl.h>
#include <sys/types.h>
static std::string process_name;
static uid_t process_uid;
static constexpr int AID_USER_OFFSET = 100000, AID_APP_START = 10000;
static int raw_openat(const char*, int) { return 7; }
static int raw_close(int) { return 0; }
static ssize_t raw_read(int, void* dest, size_t size) {
    size_t n = std::min(size, process_name.size() + 1);
    std::memcpy(dest, process_name.c_str(), n);
    return static_cast<ssize_t>(n);
}
static uid_t mock_getuid() { return process_uid; }
#define getuid mock_getuid
@@PRODUCTION@@
int main() {
    struct Case { const char* name; uid_t uid; bool filtered; };
    const Case cases[] = {
        {"com.android.permissioncontroller", 10336, false},
        {"com.android.permissioncontroller:service", 10336, false},
        {"com.android.permissioncontroller", 1010336, false},
        {"ordinary.app", 10417, true},
        {"ordinary.app", 1010417, true},
        {"com.android.permissioncontroller.extra", 10417, true},
        {"com.google.android.permissioncontroller", 10336, true},
        {"org.lineageos.updater", 10020, false},
        {"system_server", 1000, false},
        {"root", 0, false},
        {"zygote64", 10000, false},
    };
    int failed = 0;
    for (const auto& c : cases) {
        process_name = c.name;
        process_uid = c.uid;
        if (is_app_process() != c.filtered) {
            ++failed; std::cout << "FAIL " << c.name << " uid=" << c.uid << '\n';
        }
    }
    std::cout << "filtering cases: passed=" << 11-failed << " failed=" << failed << '\n';
    return failed ? 1 : 0;
}
'''


def cpp_function(source, name):
    code = guard.code_only(source)
    match = re.search(r"static bool " + name + r"\([^)]*\)\s*\{", code)
    start = code.index("{", match.start())
    return source[match.start():guard.block_end(code, start)]


@unittest.skipUnless(os.environ.get("ONYX_USERSPACE_TEST_ROM") and
                     os.environ.get("ONYX_ANDROID_TEST_JAR"), "requires isolated source and android-all jar")
class ProductionBehavior(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom = Path(os.environ["ONYX_USERSPACE_TEST_ROM"])
        cls.android_jar = Path(os.environ["ONYX_ANDROID_TEST_JAR"])
        for tool in ("javac", "java", "g++"):
            if not shutil.which(tool):
                raise RuntimeError(f"required behavior-check tool is missing: {tool}")
        if os.environ.get("ONYX_USERSPACE_TEST_OUT"):
            cls.work = Path(os.environ["ONYX_USERSPACE_TEST_OUT"])
            cls.work.mkdir(parents=True, exist_ok=True)
        else:
            cls.temp = tempfile.TemporaryDirectory(prefix="onyx-behavior-")
            cls.addClassCleanup(cls.temp.cleanup)
            cls.work = Path(cls.temp.name)

    def sources(self, project, path):
        yield "baseline", subprocess.check_output(
            ["git", "-C", str(self.rom / project), "show", f"HEAD:{path}"], text=True)
        yield "patched", (self.rom / project / path).read_text()

    def run_logged(self, command, directory, log):
        result = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=45)
        (directory / log).write_text(result.stdout + result.stderr)
        return result

    def test_trickystore_production_authorization(self):
        for variant, source in self.sources("frameworks/base", guard.SOURCES[guard.TRICKYSTORE_PATCH]):
            with self.subTest(variant=variant):
                span = guard.method_span(source, "canReadTrickyStoreKeybox")
                self.assertIsNotNone(span)
                method = source[span[0]:span[1]]
                directory = self.work / ("java-" + variant)
                directory.mkdir(exist_ok=True)
                java_file = directory / "TrickyStorePermissionHarness.java"
                java_file.write_text(JAVA.replace("@@METHOD@@", method))
                compile_result = self.run_logged(
                    ["javac", "-J-Xmx256m", "-cp", str(self.android_jar), str(java_file)],
                    directory, "compile.log")
                self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
                result = self.run_logged(
                    ["java", "-Xmx128m", "-cp", str(directory) + os.pathsep + str(self.android_jar),
                     "TrickyStorePermissionHarness"], directory, "behavior.log")
                if variant == "baseline" and guard.trickystore_state(source) == "needed":
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("SecurityException: cross-user query", result.stdout)
                else:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("passed=18 failed=0", result.stdout)

    def test_bionic_production_process_classification(self):
        for variant, source in self.sources("bionic", guard.SOURCES[guard.PERMISSION_PATCH]):
            with self.subTest(variant=variant):
                array = re.search(r"static const char\* const kAllowlistedPackages\[\] = \{.*?\};",
                                  source, re.S)
                self.assertIsNotNone(array)
                functions = [cpp_function(source, name) for name in
                             ("read_cmdline_name", "name_is_zygote", "compute_exempt")]
                # Recompute between modeled processes instead of retaining the
                # real process's PID cache, which is outside the changed logic.
                functions += ["static bool is_exempt_process() { bool z; return compute_exempt(&z); }",
                              cpp_function(source, "is_app_process")]
                directory = self.work / ("cpp-" + variant)
                directory.mkdir(exist_ok=True)
                cpp_file = directory / "hiding.cpp"
                cpp_file.write_text(CPP.replace("@@PRODUCTION@@", array[0] + "\n" + "\n".join(functions)))
                compile_result = self.run_logged(
                    ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", str(cpp_file),
                     "-o", str(directory / "hiding")], directory, "compile.log")
                self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
                result = self.run_logged([str(directory / "hiding")], directory, "behavior.log")
                if variant == "baseline" and guard.permission_state(source) == "needed":
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("passed=8 failed=3", result.stdout)
                else:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("passed=11 failed=0", result.stdout)


if __name__ == "__main__":
    unittest.main()
