#!/usr/bin/env python3
"""Exercise the actual module shell guards with sandboxed Android command adapters."""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
SHELL = os.environ.get("ONYX_GUARD_TEST_SHELL", "bash")
TARGETS = (
    "/system/framework/services.jar",
    "/vendor/etc/displayconfig/display_id_4630947173316895379.xml",
    "/vendor/etc/displayconfig/display_id_4630947258895476883.xml",
)
SYSTEMUI = "/system_ext/priv-app/SystemUIGoogle/SystemUIGoogle.apk"
SYSTEMUI_ARCHIVE = "system" + SYSTEMUI


class ModuleGuardsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="onyx-module-guards-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.module = self.root / "module"
        self.state = self.root / "state"
        self.bin = self.root / "bin"
        shutil.copytree(HERE / "module-template", self.module)
        self.state.mkdir()
        self.bin.mkdir()
        (self.module / "module.prop").write_text("id=onyx_stock_brightness_test\n")
        (self.module / "compatibility.prop").write_text(
            "ONYX_DEVICE=onyx\nONYX_INCREMENTAL=1794595788\nONYX_SDK=37\n")
        self.write_manifests()
        for name in ("common.sh", "guard-service.sh"):
            shutil.copy2(self.module / name, self.state / name)
        self.command("getprop", """case "$1" in
ro.product.device) echo "${ONYX_TEST_DEVICE:-onyx}";;
ro.build.version.incremental) echo "${ONYX_TEST_BUILD:-1794595788}";;
ro.build.version.sdk) echo 37;;
sys.boot_completed) echo "${ONYX_TEST_BOOT_COMPLETED:-1}";;
esac""")
        self.command("pidof", """if [ "$1" = com.android.systemui ]; then
  [ "${ONYX_TEST_SYSTEMUI_STARTED:-1}" = 1 ] || exit 1
  echo 4343; exit 0
fi
[ "${ONYX_TEST_FRAMEWORK_STARTED:-0}" = 1 ] || exit 1
echo 4242""")
        self.command("sha256sum", """if [ "$1" = -c ]; then
case "$2" in
*/baseline.sha256|*/payload.sha256)
  case "$2" in *"${ONYX_TEST_FAIL_MANIFEST:-impossible}"*) exit 1;; esac
  exit 0;;
esac
fi
exec /usr/bin/sha256sum "$@"
""")
        self.command("ksud", """echo "$*" >> "$ONYX_STATE/ksud-calls"
[ "${ONYX_TEST_KSUD_FAIL:-0}" != 1 ] || exit 1
[ "$1 $2" != 'module enable' ] || rm -f "$ONYX_MOD/disable"
""")
        self.command("reboot", "touch \"$ONYX_STATE/reboot-called\"")
        self.command("busybox", """case "$1" in
chcon|setsid) echo "$*" >> "$ONYX_STATE/busybox-calls";;
*) exit 1;;
esac""")
        self.command("timeout", """if [ "${ONYX_TEST_DUMP_TIMEOUT:-0}" = 1 ] \
        && [ "$2" = dumpsys ]; then exit 124; fi
if [ "${ONYX_TEST_SYSTEMUI_TIMEOUT:-0}" = 1 ] \
        && [ "$2 $3" = 'dumpsys activity' ]; then exit 124; fi
shift
exec "$@"
""")
        self.command("sleep", ":")
        self.command("logcat", "printf '%s\\n' \"${ONYX_TEST_CRASH:-}\"")
        self.command("dumpsys", """if [ "$1" = activity ]; then
  if [ "${ONYX_TEST_SYSTEMUI_DUMP_FAILURE:-0}" = 1 ]; then
    printf '%s\\n' 'SERVICE com.android.systemui/.SystemUIService 123 pid=4343' \
      '  Client:' '    Failure while dumping the service: java.io.IOException: Timeout'
    exit 0
  fi
  [ "${ONYX_TEST_MISSING_SYSTEMUI_SERVICE:-0}" = 0 ] \
    && printf '%s\\n' 'SERVICE com.android.systemui/.SystemUIService 123 pid=4343' \
      '  Client:' '    Dump starting: 11-14 00:00:00.000' || echo 'No services'
  [ "${ONYX_TEST_MISSING_SYSTEMUI_COMPLETION:-0}" != 0 ] || echo '    Dump took 2ms'
  exit 0
fi
[ "${ONYX_TEST_MISSING_MARKER:-0}" = 0 ] \
&& echo 'Onyx sensors: assist=33171055, pocket=33171027' || echo 'No port'""")
        self.command("getenforce", "echo \"${ONYX_TEST_SELINUX:-Enforcing}\"")
        self.env = {
            **os.environ,
            "PATH": str(self.bin) + ":" + os.environ["PATH"],
            "ONYX_MOD": str(self.module),
            "ONYX_STATE": str(self.state),
            "ONYX_KSUD": str(self.bin / "ksud"),
            "ONYX_REBOOT": str(self.bin / "reboot"),
            "ONYX_BUSYBOX": str(self.bin / "busybox"),
            "ONYX_WATCHER": str(self.root / "service.d/watchdog.sh"),
        }
        self.boot = Path("/proc/sys/kernel/random/boot_id").read_text()

    def refresh_assets(self):
        entries = []
        for path in sorted(self.module.iterdir()):
            if path.is_file() and path.name not in ("customize.sh", "assets.sha256", "disable"):
                entries.append(hashlib.sha256(path.read_bytes()).hexdigest()
                               + "  " + path.name + "\n")
        (self.module / "assets.sha256").write_text("".join(entries))

    def write_manifests(self, systemui=False):
        installed, archive = [], []
        for index, name in enumerate(TARGETS + ((SYSTEMUI,) if systemui else ())):
            relative = SYSTEMUI_ARCHIVE if name == SYSTEMUI else name.lstrip("/")
            path = self.module / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"sandbox payload {index}\n")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            installed.append(f"{digest}  {name}\n")
            archive.append(f"{digest}  {relative}\n")
        for name in ("baseline.sha256", "payload.sha256"):
            (self.module / name).write_text("".join(installed))
        (self.module / "archive-payload.sha256").write_text("".join(archive))
        self.refresh_assets()

    def systemui(self):
        self.write_manifests(systemui=True)

    def command(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o755)

    def run_script(self, name, **extra):
        return subprocess.run([SHELL, str(self.module / name)], env={**self.env, **extra},
                              text=True, capture_output=True, timeout=30)

    def run_customizer(self):
        adapters = """abort() { echo "$*" >&2; exit 1; }
set_perm_recursive() { :; }
set_perm() { :; }
ui_print() { echo "$*"; }
. "$MODPATH/customize.sh"
"""
        return subprocess.run([SHELL, "-c", adapters],
                              env={**self.env, "MODPATH": str(self.module), "KSU": "true"},
                              text=True, capture_output=True, timeout=30)

    def armed(self):
        (self.state / "armed").touch()

    def mounted(self):
        self.armed()
        (self.state / "prepared-boot").write_text(self.boot)
        (self.state / "mounted-boot").write_text(self.boot)
        (self.state / "logcat-since").write_text("11-14 00:00:00.000\n")

    def assert_rejected_before_mount(self, **env):
        self.armed()
        result = self.run_script("post-fs-data.sh", **env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.module / "disable").exists())
        self.assertTrue((self.state / "failure").exists())
        self.assertFalse((self.state / "prepared-boot").exists())
        self.assertFalse((self.state / "reboot-called").exists())

    def test_wrong_build_rejects_without_mount_or_reboot(self):
        self.assert_rejected_before_mount(ONYX_TEST_BUILD="wrong")

    def test_changed_base_artifact_rejects_before_mount(self):
        self.assert_rejected_before_mount(ONYX_TEST_FAIL_MANIFEST="baseline.sha256")

    def test_late_framework_mount_rejects_before_mount(self):
        self.assert_rejected_before_mount(ONYX_TEST_FRAMEWORK_STARTED="1")

    def test_tampered_script_rejects_before_mount(self):
        with (self.module / "accept.sh").open("a") as out:
            out.write("# damaged\n")
        self.assert_rejected_before_mount()

    def test_valid_preflight_records_current_boot(self):
        self.armed()
        result = self.run_script("post-fs-data.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.state / "prepared-boot").read_text(), self.boot)
        self.assertFalse((self.module / "disable").exists())

    def test_unverified_prior_attempt_disables_before_next_mount(self):
        self.armed()
        (self.state / "prepared-boot").write_text("previous-boot\n")
        result = self.run_script("post-fs-data.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.module / "disable").exists())
        self.assertIn("Previous brightness boot", (self.state / "failure").read_text())
        self.assertEqual((self.state / "prepared-boot").read_text(), "previous-boot\n")

    def test_accepted_prior_boot_requires_its_health_verification(self):
        self.armed()
        (self.state / "accepted").touch()
        (self.state / "prepared-boot").write_text("previous-boot\n")
        (self.state / "health-verified-boot").write_text("older-boot\n")
        result = self.run_script("post-fs-data.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.module / "disable").exists())

    def test_arm_clears_staged_disable_only_after_enable_succeeds(self):
        (self.module / "disable").touch()
        result = self.run_script("arm.sh")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.state / "armed").exists())
        self.assertFalse((self.module / "disable").exists())

    def test_failed_arm_enable_keeps_staged_disable(self):
        (self.module / "disable").touch()
        result = self.run_script("arm.sh", ONYX_TEST_KSUD_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.module / "disable").exists())

    def test_damaged_archive_cannot_arm(self):
        (self.module / "disable").touch()
        (self.module / "system/framework/services.jar").write_text("corrupt\n")
        result = self.run_script("arm.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.state / "armed").exists())
        self.assertTrue((self.module / "disable").exists())

    def test_post_mount_installs_next_boot_disable_marker(self):
        self.mounted()
        result = self.run_script("post-mount.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.module / "disable").exists())
        self.assertEqual((self.state / "mounted-boot").read_text(), self.boot)

    def test_post_mount_hash_failure_disables_and_reboots(self):
        self.mounted()
        result = self.run_script("post-mount.sh", ONYX_TEST_FAIL_MANIFEST="payload.sha256")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.module / "disable").exists())
        self.assertTrue((self.state / "reboot-called").exists())

    def test_guard_accepts_healthy_port_without_rejecting_unrelated_app_crash(self):
        self.mounted()
        (self.state / "accepted").touch()
        result = self.run_script("guard-service.sh", ONYX_TEST_FRAMEWORK_STARTED="1",
                                 ONYX_TEST_CRASH="AndroidRuntime: Process: unrelated.app, PID: 4")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.state / "health-verified-boot").read_text(), self.boot)
        self.assertFalse((self.state / "reboot-called").exists())

    def test_guard_detects_system_server_crash(self):
        self.mounted()
        result = self.run_script("guard-service.sh", ONYX_TEST_FRAMEWORK_STARTED="1",
                                 ONYX_TEST_CRASH="FATAL EXCEPTION IN SYSTEM PROCESS: DisplayPower")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.module / "disable").exists())
        self.assertTrue((self.state / "reboot-called").exists())

    def test_guard_requires_runtime_port_marker(self):
        self.mounted()
        result = self.run_script("guard-service.sh", ONYX_TEST_FRAMEWORK_STARTED="1",
                                 ONYX_TEST_MISSING_MARKER="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.state / "reboot-called").exists())

    def test_guard_reboots_if_display_service_query_times_out(self):
        self.mounted()
        result = self.run_script("guard-service.sh", ONYX_TEST_FRAMEWORK_STARTED="1",
                                 ONYX_TEST_DUMP_TIMEOUT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("twenty seconds", (self.state / "failure").read_text())
        self.assertTrue((self.state / "reboot-called").exists())

    def test_guard_recovers_unaccepted_trial_after_deadline(self):
        self.mounted()
        result = self.run_script("guard-service.sh", ONYX_TEST_FRAMEWORK_STARTED="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fifteen minutes", (self.state / "failure").read_text())
        self.assertTrue((self.state / "reboot-called").exists())

    def test_accept_requires_health_marker_from_same_boot(self):
        self.mounted()
        (self.module / "disable").touch()
        (self.state / "health-verified-boot").write_text("stale-boot\n")
        result = self.run_script("accept.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.state / "accepted").exists())
        self.assertTrue((self.module / "disable").exists())

    def test_accept_enables_only_verified_enforcing_trial(self):
        self.mounted()
        (self.module / "disable").touch()
        (self.state / "health-verified-boot").write_text(self.boot)
        result = self.run_script("accept.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.state / "accepted").exists())
        self.assertFalse((self.module / "disable").exists())

    def test_accept_refuses_permissive_selinux(self):
        self.mounted()
        (self.module / "disable").touch()
        (self.state / "health-verified-boot").write_text(self.boot)
        result = self.run_script("accept.sh", ONYX_TEST_SELINUX="Permissive")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.state / "accepted").exists())
        self.assertTrue((self.module / "disable").exists())

    def test_rollback_preserves_baseline_and_disables_next_boot(self):
        self.mounted()
        (self.state / "accepted").touch()
        result = self.run_script("rollback.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.module / "disable").exists())
        self.assertFalse((self.state / "armed").exists())
        self.assertFalse((self.state / "accepted").exists())
        self.assertFalse((self.state / "reboot-called").exists())

    def test_manifest_rejects_fourth_framework_payload(self):
        bad = self.root / "bad.sha256"
        bad.write_text((self.module / "baseline.sha256").read_text()
                       + "0" * 64 + "  /system/framework/framework-res.apk\n")
        command = '. "$ONYX_MOD/common.sh"; onyx_manifest_format "$1"'
        result = subprocess.run([SHELL, "-c", command, "test", str(bad)], env=self.env)
        self.assertNotEqual(result.returncode, 0)

    def test_four_file_preflight_accepts_exact_systemui_path(self):
        self.systemui()
        self.armed()
        result = self.run_script("post-fs-data.sh")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.state / "prepared-boot").read_text(), self.boot)
        self.assertFalse((self.module / "disable").exists())

    def test_installer_accepts_and_labels_four_file_payload_while_disabled(self):
        self.systemui()
        result = self.run_customizer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.module / "disable").exists())
        self.assertFalse((self.state / "armed").exists())
        self.assertTrue(Path(self.env["ONYX_WATCHER"]).exists())
        self.assertIn(f"chcon --reference={SYSTEMUI} ",
                      (self.state / "busybox-calls").read_text())

    def test_installer_rejects_unlisted_systemui_payload(self):
        path = self.module / SYSTEMUI_ARCHIVE
        path.parent.mkdir(parents=True)
        path.write_text("unlisted SystemUI\n")
        result = self.run_customizer()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(Path(self.env["ONYX_WATCHER"]).exists())
        self.assertIn("unlisted files", result.stderr)

    def test_systemui_payload_requires_its_baseline_entry(self):
        self.systemui()
        path = self.module / "baseline.sha256"
        path.write_text("".join(line for line in path.read_text().splitlines(True)
                                if SYSTEMUI not in line))
        self.refresh_assets()
        self.assert_rejected_before_mount()

    def test_systemui_baseline_requires_its_payload_entry(self):
        self.systemui()
        path = self.module / "payload.sha256"
        path.write_text("".join(line for line in path.read_text().splitlines(True)
                                if SYSTEMUI not in line))
        self.refresh_assets()
        self.assert_rejected_before_mount()

    def test_systemui_archive_must_match_installed_payload_hash(self):
        self.systemui()
        path = self.module / "archive-payload.sha256"
        entries = path.read_text().splitlines(True)
        entries[-1] = "0" * 64 + f"  {SYSTEMUI_ARCHIVE}\n"
        path.write_text("".join(entries))
        self.refresh_assets()
        self.assert_rejected_before_mount()

    def test_systemui_archive_cannot_use_unmapped_partition_path(self):
        self.systemui()
        path = self.module / "archive-payload.sha256"
        path.write_text(path.read_text().replace(SYSTEMUI_ARCHIVE, SYSTEMUI.lstrip("/")))
        self.refresh_assets()
        self.assert_rejected_before_mount()

    def test_systemui_manifest_rejects_duplicate_entry(self):
        self.systemui()
        path = self.module / "payload.sha256"
        with path.open("a") as out:
            out.write(path.read_text().splitlines(True)[-1])
        self.refresh_assets()
        self.assert_rejected_before_mount()

    def test_unlisted_systemui_apk_rejects_before_mount(self):
        path = self.module / SYSTEMUI_ARCHIVE
        path.parent.mkdir(parents=True)
        path.write_text("unlisted SystemUI\n")
        self.assert_rejected_before_mount()

    def test_unlisted_overlay_file_rejects_before_mount(self):
        path = self.module / "system/framework/framework-res.apk"
        path.write_text("unlisted framework APK\n")
        self.assert_rejected_before_mount()

    def test_unlisted_dangling_systemui_symlink_rejects_before_mount(self):
        path = self.module / SYSTEMUI_ARCHIVE
        path.parent.mkdir(parents=True)
        path.symlink_to("missing.apk")
        self.assert_rejected_before_mount()

    def test_dangling_partition_symlink_rejects_before_mount(self):
        (self.module / "system_ext").symlink_to("missing-partition", target_is_directory=True)
        self.assert_rejected_before_mount()

    def test_nonregular_declared_payload_rejects_before_hashing(self):
        path = self.module / "system/framework/services.jar"
        path.unlink()
        os.mkfifo(path)
        self.assert_rejected_before_mount()

    def test_normalized_system_ext_and_vendor_links_preserve_archive_check(self):
        self.systemui()
        shutil.move(self.module / "system/system_ext", self.module / "system_ext")
        (self.module / "system/system_ext").symlink_to("../system_ext", target_is_directory=True)
        (self.module / "system/vendor").symlink_to("../vendor", target_is_directory=True)
        self.armed()
        result = self.run_script("post-fs-data.sh")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.state / "prepared-boot").read_text(), self.boot)
        self.assertFalse((self.module / "disable").exists())

    def test_independent_system_ext_alias_payload_rejects_before_mount(self):
        self.systemui()
        shutil.copytree(self.module / "system/system_ext", self.module / "system_ext")
        self.assert_rejected_before_mount()

    def test_independent_vendor_alias_payload_rejects_before_mount(self):
        shutil.copytree(self.module / "vendor", self.module / "system/vendor")
        self.assert_rejected_before_mount()

    def test_damaged_systemui_archive_cannot_arm(self):
        self.systemui()
        (self.module / "disable").touch()
        (self.module / SYSTEMUI_ARCHIVE).write_text("corrupt\n")
        result = self.run_script("arm.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.state / "armed").exists())
        self.assertTrue((self.module / "disable").exists())

    def test_systemui_labels_reference_installed_system_ext_path(self):
        self.systemui()
        result = self.run_script("arm.sh")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = (self.state / "busybox-calls").read_text()
        self.assertIn(f"chcon --reference={SYSTEMUI} {self.module / SYSTEMUI_ARCHIVE}\n", calls)
        self.assertIn("chcon --reference=/system_ext ", calls)

    def test_guard_verifies_healthy_systemui_in_same_boot(self):
        self.systemui()
        self.mounted()
        (self.state / "accepted").touch()
        result = self.run_script("guard-service.sh", ONYX_TEST_FRAMEWORK_STARTED="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.state / "systemui-verified-boot").read_text(), self.boot)
        self.assertFalse((self.state / "reboot-called").exists())

    def test_guard_rolls_back_systemui_java_and_native_crashes(self):
        for crash in ("AndroidRuntime: Process: com.android.systemui, PID: 42",
                      "DEBUG: >>> com.android.systemui <<<",
                      "AndroidRuntime: Process: com.android.systemui:screenrecord, PID: 42"):
            with self.subTest(crash=crash):
                self.systemui()
                self.mounted()
                result = self.run_script("guard-service.sh", ONYX_TEST_FRAMEWORK_STARTED="1",
                                         ONYX_TEST_CRASH=crash)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("SystemUI crashed", (self.state / "failure").read_text())
                self.assertTrue((self.state / "reboot-called").exists())

    def test_guard_requires_systemui_process_for_boot_health(self):
        self.systemui()
        self.mounted()
        result = self.run_script("guard-service.sh", ONYX_TEST_FRAMEWORK_STARTED="1",
                                 ONYX_TEST_SYSTEMUI_STARTED="0")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.state / "health-verified-boot").exists())
        self.assertFalse((self.state / "systemui-verified-boot").exists())
        self.assertTrue((self.state / "reboot-called").exists())

    def test_guard_requires_systemui_service_and_bounds_query(self):
        for env in ({"ONYX_TEST_MISSING_SYSTEMUI_SERVICE": "1"},
                    {"ONYX_TEST_SYSTEMUI_TIMEOUT": "1"},
                    {"ONYX_TEST_SYSTEMUI_DUMP_FAILURE": "1"},
                    {"ONYX_TEST_MISSING_SYSTEMUI_COMPLETION": "1"}):
            with self.subTest(env=env):
                self.systemui()
                self.mounted()
                result = self.run_script("guard-service.sh", ONYX_TEST_FRAMEWORK_STARTED="1", **env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("SystemUI process or service", (self.state / "failure").read_text())
                self.assertFalse((self.state / "systemui-verified-boot").exists())
                self.assertTrue((self.state / "reboot-called").exists())

    def test_accept_requires_current_systemui_health_and_payload(self):
        for env, marker in (({}, "older-boot\n"),
                            ({"ONYX_TEST_SYSTEMUI_STARTED": "0"}, self.boot),
                            ({"ONYX_TEST_MISSING_SYSTEMUI_SERVICE": "1"}, self.boot),
                            ({"ONYX_TEST_SYSTEMUI_TIMEOUT": "1"}, self.boot),
                            ({"ONYX_TEST_SYSTEMUI_DUMP_FAILURE": "1"}, self.boot),
                            ({"ONYX_TEST_MISSING_SYSTEMUI_COMPLETION": "1"}, self.boot),
                            ({"ONYX_TEST_FAIL_MANIFEST": "payload.sha256"}, self.boot)):
            with self.subTest(env=env, marker=marker):
                self.systemui()
                self.mounted()
                (self.module / "disable").touch()
                (self.state / "health-verified-boot").write_text(self.boot)
                (self.state / "systemui-verified-boot").write_text(marker)
                result = self.run_script("accept.sh", **env)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.state / "accepted").exists())
                self.assertTrue((self.module / "disable").exists())

    def test_accept_enables_four_file_healthy_trial(self):
        self.systemui()
        self.mounted()
        (self.module / "disable").touch()
        (self.state / "health-verified-boot").write_text(self.boot)
        (self.state / "systemui-verified-boot").write_text(self.boot)
        result = self.run_script("accept.sh")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.state / "accepted").exists())
        self.assertFalse((self.module / "disable").exists())

    def test_failed_accept_enable_keeps_trial_unaccepted(self):
        self.mounted()
        (self.module / "disable").touch()
        (self.state / "health-verified-boot").write_text(self.boot)
        result = self.run_script("accept.sh", ONYX_TEST_KSUD_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.state / "accepted").exists())
        self.assertTrue((self.module / "disable").exists())

    def test_accepted_prior_systemui_boot_requires_its_health_marker(self):
        self.systemui()
        self.armed()
        (self.state / "accepted").touch()
        (self.state / "prepared-boot").write_text("previous-boot\n")
        (self.state / "health-verified-boot").write_text("previous-boot\n")
        (self.state / "systemui-verified-boot").write_text("older-boot\n")
        result = self.run_script("post-fs-data.sh")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.module / "disable").exists())
        self.assertIn("Previous SystemUI boot", (self.state / "failure").read_text())


if __name__ == "__main__":
    unittest.main()
