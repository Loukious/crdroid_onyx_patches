"""Exercise upstream detection and the real apply.sh entry point in tiny trees."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("upstream_fix_state", ROOT / "ci/upstream_fix_state.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

BIONIC = '''static const char* const kMountFilterKeywords[] = {
    "/debug_ramdisk", "overlay", "magisk", "ksu", "KSU", "ksud", "apatch", "/data/adb", nullptr
};

static const char* const kAllowlistedPackages[] = {
    "org.lineageos.updater",
    nullptr
};

#define DM_MAJOR 253u
'''

VULNERABLE_CHECK = '''        if (UserHandle.getUserId(uid) != ActivityManager.getCurrentUser()
                && UserHandle.getUserId(uid) != UserHandle.USER_SYSTEM) return false;'''

# The original authorization method, with only its unrelated target parser
# shortened. Retain the patch context and Binder call that failed on the phone.
FRAMEWORK = '''class AxSpoofManager {
    private boolean canReadTrickyStoreKeybox() {
        int uid = Binder.getCallingUid();
        if (uid == android.os.Process.SYSTEM_UID || uid == android.os.Process.ROOT_UID) return true;
CHECK
        String[] packages = mContext.getPackageManager().getPackagesForUid(uid);
        if (packages == null) return false;
        for (String pkg : packages) {
            if (TrickyStoreService.XPOSED_PACKAGES.contains(pkg)) return false;
        }
        return isTargeted(packages);
    }

    String getTrickyStoreKeyBox() {
        if (!canReadTrickyStoreKeybox()) return null;
        long token = Binder.clearCallingIdentity();
        try {
            return duck.getKeybox();
        } finally {
            Binder.restoreCallingIdentity(token);
        }
    }
}
'''.replace("CHECK", VULNERABLE_CHECK)


def scoped_check():
    # An equivalent upstream fix that deliberately differs from our patch.
    return '''        long identity = Binder.clearCallingIdentity();
        try {
''' + VULNERABLE_CHECK + '''
        } finally {
            Binder.restoreCallingIdentity(identity);
        }'''


class UpstreamState(unittest.TestCase):
    def test_baseline_is_needed_despite_clear_identity_in_another_method(self):
        self.assertEqual(guard.trickystore_state(FRAMEWORK), "needed")
        self.assertEqual(guard.permission_state(BIONIC), "needed")

    def test_existing_permissioncontroller_exemption(self):
        source = BIONIC.replace('"org.lineageos.updater",',
                                '"org.lineageos.updater",\n    "com.android.permissioncontroller",')
        self.assertEqual(guard.permission_state(source), "upstream")

    def test_comment_does_not_count_as_an_exemption(self):
        source = BIONIC.replace('"org.lineageos.updater",',
                                '"org.lineageos.updater", // "com.android.permissioncontroller"')
        self.assertEqual(guard.permission_state(source), "needed")

    def test_unknown_bionic_layout_requires_review(self):
        with self.assertRaises(ValueError):
            guard.permission_state("bool replacement_hiding_implementation();")

    def test_equivalent_scoped_binder_fix(self):
        self.assertEqual(guard.trickystore_state(
            FRAMEWORK.replace(VULNERABLE_CHECK, scoped_check())), "upstream")

    def test_internal_accessor_replacement(self):
        source = FRAMEWORK.replace("ActivityManager.getCurrentUser()",
                                   "mActivityManagerInternal.getCurrentUserId()")
        self.assertEqual(guard.trickystore_state(source), "upstream")

    def test_clean_identity_lambda_replacement(self):
        source = FRAMEWORK.replace("ActivityManager.getCurrentUser()",
            "Binder.withCleanCallingIdentity(() -> ActivityManager.getCurrentUser())")
        self.assertEqual(guard.trickystore_state(source), "upstream")

    def test_clear_and_restore_before_query_is_not_a_fix(self):
        source = FRAMEWORK.replace(VULNERABLE_CHECK,
            "        long token = Binder.clearCallingIdentity();\n"
            "        Binder.restoreCallingIdentity(token);\n" + VULNERABLE_CHECK)
        self.assertEqual(guard.trickystore_state(source), "needed")

    def test_wrong_restore_token_is_not_accepted(self):
        source = FRAMEWORK.replace(VULNERABLE_CHECK,
                                   scoped_check().replace("restoreCallingIdentity(identity)",
                                                          "restoreCallingIdentity(other)"))
        self.assertEqual(guard.trickystore_state(source), "needed")

    def test_capturing_system_uid_after_clear_is_not_accepted(self):
        source = FRAMEWORK.replace("        int uid = Binder.getCallingUid();\n", "")
        source = source.replace(VULNERABLE_CHECK, scoped_check().replace(
            "        try {", "        try {\n            int uid = Binder.getCallingUid();"))
        self.assertEqual(guard.trickystore_state(source), "needed")

    def test_comments_and_strings_do_not_change_method_boundaries(self):
        source = FRAMEWORK.replace("        int uid =", '''        // } Binder.clearCallingIdentity();
        String unrelated = "} ActivityManager.getCurrentUser()";
        /* } finally { Binder.restoreCallingIdentity(token); } */
        int uid =''')
        self.assertEqual(guard.trickystore_state(source), "needed")

    def test_removed_implementation_is_obsolete(self):
        self.assertEqual(guard.trickystore_state("class AxSpoofManager {}"), "obsolete")
        self.assertEqual(guard.trickystore_state(None), "obsolete")
        self.assertEqual(guard.permission_state(None), "obsolete")


class PatchApplication(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="onyx-upstream-test-")
        self.addCleanup(self.temp.cleanup)
        top = Path(self.temp.name)
        self.rom = top / "rom"
        (self.rom / ".repo").mkdir(parents=True)
        self.patches = top / "patches"
        (self.patches / "ci").mkdir(parents=True)
        shutil.copyfile(ROOT / "apply.sh", self.patches / "apply.sh")
        for name in ("upstream_fix_state.py", "check-patched-xml.py"):
            shutil.copyfile(ROOT / "ci" / name, self.patches / "ci" / name)
        for key in guard.SOURCES:
            target = self.patches / "patches" / key
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "patches" / key, target)
        self.bionic = self.rom / "bionic" / guard.SOURCES[guard.PERMISSION_PATCH]
        self.framework = self.rom / "frameworks/base" / guard.SOURCES[guard.TRICKYSTORE_PATCH]
        for path, source in ((self.bionic, BIONIC), (self.framework, FRAMEWORK)):
            path.parent.mkdir(parents=True)
            path.write_text(source)
        for project in (self.rom / "bionic", self.rom / "frameworks/base"):
            subprocess.run(["git", "init", "-q", str(project)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(project), "add", "."], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(project), "-c", "user.name=Patch tests",
                            "-c", "user.email=tests@localhost", "-c", "commit.gpgsign=false",
                            "commit", "-qm", "Fixture"], check=True, capture_output=True)

    def apply(self, success=True):
        env = dict(os.environ, KONOHA_SOURCE_BUILD="0", SKIP_KERNEL="1",
                   SKIP_WLAN="1", SKIP_FIRMWARE="1", SKIP_PATCHES="0")
        result = subprocess.run(["bash", str(self.patches / "apply.sh"), str(self.rom)],
                                env=env, text=True, capture_output=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def test_apply_and_repeat_without_changing_fixed_files(self):
        output = self.apply()
        self.assertIn("applied=2", output)
        before = (self.bionic.read_bytes(), self.framework.read_bytes())
        self.assertEqual(guard.trickystore_state(self.framework.read_text()), "upstream")
        self.assertIn("applied=0", self.apply())
        self.assertEqual(before, (self.bionic.read_bytes(), self.framework.read_bytes()))

    def test_existing_upstream_exemption_with_extra_entries(self):
        self.bionic.write_text(BIONIC.replace('"org.lineageos.updater",',
            '"another.upstream.process",\n    "com.android.permissioncontroller",\n'
            '    "org.lineageos.updater",'))
        before = self.bionic.read_bytes()
        self.assertIn("applied=1", self.apply())
        self.assertEqual(self.bionic.read_bytes(), before)

    def test_different_upstream_fixes_are_not_overwritten(self):
        replacements = [
            FRAMEWORK.replace("ActivityManager.getCurrentUser()",
                              "mActivityManagerInternal.getCurrentUserId()"),
            FRAMEWORK.replace(VULNERABLE_CHECK, scoped_check()),
            FRAMEWORK.replace("ActivityManager.getCurrentUser()",
                "Binder.withCleanCallingIdentity(() -> ActivityManager.getCurrentUser())"),
        ]
        for number, source in enumerate(replacements):
            with self.subTest(variant=number):
                self.framework.write_text(source)
                self.apply()
                self.assertEqual(self.framework.read_text(), source)

    def test_removed_upstream_method_is_not_reintroduced(self):
        self.framework.write_text("class AxSpoofManager {}\n")
        self.apply()
        self.assertEqual(self.framework.read_text(), "class AxSpoofManager {}\n")

    def test_unfixed_source_conflict_fails_without_fuzzy_changes(self):
        source = FRAMEWORK.replace("int uid = Binder.getCallingUid();",
                                   "int uid = checkedCallingUid();")
        self.framework.write_text(source)
        self.assertIn("exact apply required", self.apply(success=False))
        self.assertEqual(self.framework.read_text(), source)

    def test_generator_retains_patches_when_head_is_fixed_upstream(self):
        self.apply()
        for project in (self.rom / "bionic", self.rom / "frameworks/base"):
            subprocess.run(["git", "-C", str(project), "add", "."], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(project), "-c", "user.name=Patch tests",
                            "-c", "user.email=tests@localhost", "-c", "commit.gpgsign=false",
                            "commit", "-qm", "Upstream fix"], check=True, capture_output=True)
        # Load the actual generator helpers, stopping before its source-tree loop.
        prefix = (ROOT / "gen-patches.sh").read_text().split('\nPROJECTS="', 1)[0]
        script = self.patches / "gen-helpers.sh"
        script.write_text(prefix + '''
emit_upstream_fix bionic 0001-exempt-permissioncontroller-from-rom-hiding.patch \\
    'com\\.android\\.permissioncontroller' libc/bionic/custom_rom_hide.cpp
emit_upstream_fix frameworks/base 0011-trickystore-current-user-identity.patch \\
    'Resolve the foreground user|currentUserId' \\
    services/core/java/com/android/server/spoof/AxSpoofManager.java
''')
        output = Path(self.temp.name) / "generated"
        result = subprocess.run(["bash", str(script)], text=True, capture_output=True,
                                env=dict(os.environ, ROM=str(self.rom), OUT=str(output)))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for key in guard.SOURCES:
            self.assertEqual((ROOT / "patches" / key).read_bytes(),
                             (output / "patches" / key).read_bytes())


if __name__ == "__main__":
    unittest.main()
