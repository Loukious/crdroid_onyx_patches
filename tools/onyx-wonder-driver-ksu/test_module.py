#!/usr/bin/env python3
"""Host-only rejection, normal unload and rollback tests with mocked Android tools."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("driver_packager", HERE / "build-module.py")
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)
NAME = packager.NAME


class ReloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="onyx-driver-host-")
        self.root = Path(self.temporary.name)
        self.module = self.root / "module"
        self.sys = self.root / "sys"
        self.proc = self.root / "proc"
        self.vendor = self.root / "vendor"
        self.state = self.root / "state"
        self.calls = self.root / "calls"
        for path in (self.module / "payload", self.vendor, self.sys / "class/net/wlan0",
                     self.proc / "sys/kernel/random", self.state):
            path.mkdir(parents=True, exist_ok=True)
        self.stock_note = hashlib.sha256(b"stock-note").hexdigest()
        self.replacement_note = hashlib.sha256(b"replacement-note").hexdigest()
        (self.module / "payload-contract.sh").write_text(
            "WDR_REPLACEMENT_SHA=" + "b" * 64 + "\nWDR_STOCK_NOTE_SHA=" + self.stock_note +
            "\nWDR_REPLACEMENT_NOTE_SHA=" + self.replacement_note + "\n")
        (self.module / "payload" / (NAME + ".ko")).write_bytes(b"replacement")
        (self.vendor / (NAME + ".ko")).write_bytes(b"stock")
        (self.vendor / "modules.options").write_text(
            "options " + NAME + " sta_monitor_coexist=1 ap_monitor_coexist=1 "
            "sta_ap_monitor_coexist=1 wonder_enabled=1\n")
        (self.proc / "sys/kernel/random/boot_id").write_text("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\n")
        (self.proc / "modules").write_text(NAME + " 12345 0 - Live 0x0\n")
        (self.sys / "class/net/wlan0/flags").write_text("0x1002\n")
        self.driver = self.sys / "module" / NAME
        (self.driver / "holders").mkdir(parents=True)
        (self.driver / "parameters").mkdir()
        (self.driver / "notes").mkdir()
        (self.driver / "initstate").write_text("live\n")
        (self.driver / "refcnt").write_text("0\n")
        (self.driver / "notes/.note.gnu.build-id").write_bytes(b"stock-note")
        for parameter in ("sta_monitor_coexist", "ap_monitor_coexist", "sta_ap_monitor_coexist", "wonder_enabled"):
            (self.driver / "parameters" / parameter).write_text("Y\n")
        (self.driver / "parameters/wonder_coex_stats").write_text("active=0\n")

    def tearDown(self):
        self.temporary.cleanup()

    def run_shell(self, *, mode="success", stage="early", property_override="", body="wdr_reload", interpreter="sh"):
        setup = ". " + shlex.quote(str(HERE / "module-template/common.sh")) + "\n"
        property_key, property_value = property_override.split("=", 1) if property_override else ("", "")
        for name, value in (("WDR_MOD", self.module), ("WDR_SYS", self.sys), ("WDR_PROC", self.proc),
                            ("WDR_VENDOR", self.vendor), ("WDR_STATE", self.state), ("WDR_STAGE", stage),
                            ("MOCK_MODE", mode), ("MOCK_CALLS", self.calls),
                            ("MOCK_PROP_KEY", property_key), ("MOCK_PROP_VALUE", property_value)):
            setup += name + "=" + shlex.quote(str(value)) + "\n"
        setup += r'''
wdr_sha() {
    case "$1" in
        */payload/*.ko) printf '%s\n' "$WDR_REPLACEMENT_SHA";;
        *.ko) printf '%s\n' "$WDR_STOCK_SHA";;
        *) sha256sum "$1" | awk '{ print $1 }';;
    esac
}
wdr_android() {
    mock_tool=$1; shift
    case "$mock_tool" in
        id) printf '%s\n' 0;;
        uname) printf '%s\n' "$WDR_RELEASE";;
        getprop)
            if [ "$1" = "$MOCK_PROP_KEY" ]; then printf '%s\n' "$MOCK_PROP_VALUE"; return 0; fi
            case "$1" in
                ro.product.device) printf '%s\n' onyx;;
                ro.build.version.sdk) printf '%s\n' 37;;
                vendor.all.modules.ready) printf '%s\n' 1;;
                init.svc.*) printf '%s\n' stopped;;
                sys.boot_completed) printf '%s\n' 0;;
            esac;;
        log) :;;
        tr) tr "$@";;
        chcon) [ "$MOCK_MODE" != label-reject ];;
        rmmod)
            printf '%s\n' rmmod >> "$MOCK_CALLS"
            [ "$MOCK_MODE" != unload-reject ] || return 1
            rm -rf "$WDR_SYS/module/$WDR_NAME";;
        insmod)
            case "$1" in
                */payload/*) mock_loading=replacement;;
                *) mock_loading=stock;;
            esac
            printf '%s\n' "$mock_loading:$*" >> "$MOCK_CALLS"
            case "$MOCK_MODE:$mock_loading" in
                insert-reject:replacement|rollback-reject:replacement|rollback-reject:stock) return 1;;
            esac
            mock_driver="$WDR_SYS/module/$WDR_NAME"
            mkdir -p "$mock_driver/parameters" "$mock_driver/notes"
            printf '%s\n' live > "$mock_driver/initstate"
            if [ "$mock_loading" = replacement ]; then
                printf '%s\n' 1 > "$mock_driver/parameters/wonder_lifecycle_revision"
                printf '%s' replacement-note > "$mock_driver/notes/.note.gnu.build-id"
            else
                printf '%s' stock-note > "$mock_driver/notes/.note.gnu.build-id"
            fi
            case "$MOCK_MODE:$mock_loading" in
                residual-reject:replacement) return 1;;
                wrong-marker:replacement) printf '%s\n' 0 > "$mock_driver/parameters/wonder_lifecycle_revision";;
                wrong-note:replacement) printf '%s' wrong-note > "$mock_driver/notes/.note.gnu.build-id";;
            esac;;
        *) return 99;;
    esac
}
'''
        setup += "wdr_init || exit 90\n" + body + "\n"
        return subprocess.run([interpreter, "-c", setup], capture_output=True, text=True)

    def tool_calls(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def test_success_proves_revision_and_build_note_and_preserves_options(self):
        result = self.run_shell()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(2, len(self.tool_calls()))
        self.assertEqual("rmmod", self.tool_calls()[0])
        self.assertTrue(self.tool_calls()[1].endswith(
            "sta_monitor_coexist=1 ap_monitor_coexist=1 sta_ap_monitor_coexist=1 wonder_enabled=1"))
        attempt = next(path for path in self.state.iterdir() if path.is_dir())
        self.assertEqual(b"stock", (attempt / "stock.ko").read_bytes())
        self.assertEqual("Y\n", (attempt / "wonder_enabled").read_text())
        self.assertTrue((attempt / "replacement-loaded").exists())

    def test_normal_unload_rejection_never_inserts(self):
        self.assertNotEqual(0, self.run_shell(mode="unload-reject").returncode)
        self.assertEqual(["rmmod"], self.tool_calls())
        self.assertTrue(self.driver.exists())

    def test_insertion_rejection_restores_stock_with_same_options_and_disables(self):
        self.assertNotEqual(0, self.run_shell(mode="insert-reject").returncode)
        self.assertEqual(3, len(self.tool_calls()))
        self.assertTrue(self.tool_calls()[2].startswith("stock:"))
        self.assertEqual(self.tool_calls()[1].split(" ", 1)[1], self.tool_calls()[2].split(" ", 1)[1])
        self.assertTrue((self.module / "disable").exists())
        self.assertEqual(b"stock-note", (self.driver / "notes/.note.gnu.build-id").read_bytes())

    def test_failed_stock_rollback_disables_hook_and_never_retries_or_forces_unload(self):
        self.assertNotEqual(0, self.run_shell(mode="rollback-reject").returncode)
        self.assertEqual(3, len(self.tool_calls()))
        self.assertTrue(self.tool_calls()[2].startswith("stock:"))
        self.assertTrue((self.module / "disable").exists())
        self.assertFalse(self.driver.exists())
        self.assertIn("stock rollback insertion failed", (self.state / "status.log").read_text())

    def test_final_preflight_changed_refcount_or_interface_aborts_before_unload(self):
        for relative, value in (("module/" + NAME + "/refcnt", "1\n"),
                                ("class/net/wlan0/flags", "0x1003\n")):
            with self.subTest(relative=relative):
                affected = self.sys / relative
                original = affected.read_bytes()
                body = r'''
wdr_preflight_count=0
wdr_preflight_base() {
    wdr_device_matches && wdr_payload_matches && wdr_stock_matches &&
    wdr_options_match && wdr_early_quiet && wdr_unloadable
}
wdr_preflight() {
    wdr_preflight_count=$((wdr_preflight_count + 1))
    if [ "$wdr_preflight_count" = 2 ]; then
        printf '%s' ''' + shlex.quote(value) + " > " + shlex.quote(str(affected)) + r'''
    fi
    wdr_preflight_base
}
wdr_reload
'''
                self.assertNotEqual(0, self.run_shell(body=body).returncode)
                self.assertEqual([], self.tool_calls())
                affected.write_bytes(original)
                import shutil
                for path in self.state.iterdir():
                    if path.is_dir():
                        shutil.rmtree(path)

    def test_residual_rejection_and_wrong_running_proof_never_force_unload(self):
        for mode in ("residual-reject", "wrong-marker", "wrong-note"):
            with self.subTest(mode=mode):
                if (self.module / "disable").exists():
                    (self.module / "disable").unlink()
                for path in self.state.iterdir():
                    if path.is_dir():
                        import shutil
                        shutil.rmtree(path)
                # Previous trial altered the simulated running module; reset its stock note.
                (self.driver / "holders").mkdir(exist_ok=True)
                (self.driver / "refcnt").write_text("0\n")
                (self.driver / "notes/.note.gnu.build-id").write_bytes(b"stock-note")
                (self.driver / "parameters/wonder_coex_stats").write_text("active=0\n")
                for parameter in ("sta_monitor_coexist", "ap_monitor_coexist", "sta_ap_monitor_coexist", "wonder_enabled"):
                    (self.driver / "parameters" / parameter).write_text("Y\n")
                self.calls.unlink(missing_ok=True)
                self.assertNotEqual(0, self.run_shell(mode=mode).returncode)
                self.assertEqual(2, len(self.tool_calls()))
                self.assertTrue((self.module / "disable").exists())

    def test_rejected_file_label_aborts_before_unload(self):
        self.assertNotEqual(0, self.run_shell(mode="label-reject").returncode)
        self.assertEqual([], self.tool_calls())

    def test_reference_holder_active_session_and_wifi_up_each_abort(self):
        mutations = (
            (self.driver / "refcnt", "1\n"),
            (self.driver / "holders/consumer", ""),
            (self.driver / "parameters/wonder_coex_stats", "active=1\n"),
            (self.sys / "class/net/wlan0/flags", "0x1003\n"),
            (self.driver / "parameters/wonder_enabled", "N\n"),
        )
        for path, value in mutations:
            with self.subTest(path=path.name):
                old = path.read_bytes() if path.exists() else None
                path.write_text(value)
                self.assertNotEqual(0, self.run_shell().returncode)
                self.assertEqual([], self.tool_calls())
                path.write_bytes(old) if old is not None else path.unlink()

    def test_provider_process_and_unreviewed_vendor_options_abort(self):
        process = self.proc / "321/cmdline"
        process.parent.mkdir()
        process.write_bytes(b"com.google.android.mosey\0")
        self.assertNotEqual(0, self.run_shell().returncode)
        process.unlink()
        options = self.vendor / "modules.options"
        options.write_text(options.read_text().strip() + " unknown_parameter=1\n")
        self.assertNotEqual(0, self.run_shell().returncode)
        self.assertEqual([], self.tool_calls())

    def test_residual_wifi_hal_process_aborts_even_when_init_property_is_stopped(self):
        process = self.proc / "322/cmdline"
        process.parent.mkdir()
        process.write_bytes(b"/vendor/bin/hw/android.hardware.wifi-service\0")
        self.assertNotEqual(0, self.run_shell(stage="live").returncode)
        self.assertEqual([], self.tool_calls())

    def test_live_mode_omits_zygote_guard_but_keeps_radio_guards(self):
        self.assertNotEqual(0, self.run_shell(property_override="init.svc.zygote=running").returncode)
        self.assertEqual([], self.tool_calls())
        result = self.run_shell(stage="live", property_override="init.svc.zygote=running")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_live_mode_still_rejects_running_native_service(self):
        self.assertNotEqual(0, self.run_shell(stage="live", property_override="init.svc.mosey_server=running").returncode)
        self.assertEqual([], self.tool_calls())

    def test_live_mode_accepts_completed_boot_and_keeps_all_radio_guards(self):
        result = self.run_shell(stage="live", property_override="sys.boot_completed=1")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_early_mode_allows_unstarted_zygote_but_rejects_residual_zygote_process(self):
        self.assertEqual(0, self.run_shell(property_override="init.svc.zygote=", body="wdr_preflight").returncode)
        comm = self.proc / "323/comm"
        comm.parent.mkdir()
        comm.write_text("zygote64\n")
        self.assertNotEqual(0, self.run_shell(property_override="init.svc.zygote=").returncode)
        self.assertEqual([], self.tool_calls())

    def test_repeated_attempt_this_boot_is_skipped(self):
        result = self.run_shell(body="wdr_reload; wdr_reload")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(2, len(self.tool_calls()))


class PackagerTests(unittest.TestCase):
    def test_example_clearance_rejects_before_any_archive_is_written(self):
        with tempfile.TemporaryDirectory(prefix="driver-package-host-") as temporary:
            root = Path(temporary)
            for name in ("module.ko", "stock.ko", "replacement.symvers"):
                (root / name).write_bytes(b"unreviewed")
            output = root / "module.zip"
            with self.assertRaisesRegex(ValueError, "reviewer-authored"):
                packager.build(output, root / "module.ko", root / "stock.ko", root / "replacement.symvers",
                               root, root, HERE / "clearance.example.json")
            self.assertFalse(output.exists())

    def test_non_arm64_or_non_relocatable_elf_rejects(self):
        with self.assertRaises(ValueError):
            packager.sections(b"not an ELF module")

    def test_scripts_parse_with_sh_and_bash(self):
        scripts = list((HERE / "module-template").glob("*.sh")) + [HERE / "live-test.sh"]
        for interpreter in ("sh", "bash"):
            for script in scripts:
                subprocess.run([interpreter, "-n", str(script)], check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
