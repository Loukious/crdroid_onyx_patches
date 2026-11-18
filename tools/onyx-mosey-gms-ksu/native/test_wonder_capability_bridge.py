#!/usr/bin/env python3
"""Offline regressions for the actual Mosey Binder capability bridge.

The fixture includes the maintained assets source with mocked Binder, log,
symbol-resolution, and Wonder query APIs. Strict GCC and ASan/UBSan runs check
wire bytes, query freshness, fail-closed behavior, and hook activation. These
host mocks do not validate Android Binder runtime or actual radio behavior.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[2] / "assets/onyx-mosey-source/files"
FIXTURE = HERE / "tests/bridge_transaction_fixture.c"
MOCK_HEADERS = HERE / "tests/bridge-include"


class WonderCapabilityBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("gcc")
        if compiler is None:
            raise RuntimeError("gcc is required for the offline bridge fixture")
        cls.before = {
            name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest()
            for name in ("wonder-capability-bridge.c", "wonder-cap-query.h")
        }
        cls.temp = tempfile.TemporaryDirectory(prefix="onyx-wonder-bridge-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.addClassCleanup(cls.check_sources_unchanged)
        cls.root = Path(cls.temp.name)
        cls.variants = ("strict", "asan-ubsan")
        flags = [
            "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wconversion",
            "-Wshadow", "-Wstrict-prototypes", "-g", "-O1",
            "-I", str(MOCK_HEADERS), "-I", str(SOURCE),
        ]
        for name in cls.variants:
            sanitizer = [] if name == "strict" else [
                "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
            ]
            result = subprocess.run(
                [compiler, *flags, *sanitizer, str(FIXTURE), "-o", str(cls.root / name)],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode:
                raise RuntimeError(name + " compilation failed:\n" + result.stderr)

    @classmethod
    def check_sources_unchanged(cls):
        after = {
            name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest()
            for name in cls.before
        }
        if after != cls.before:
            raise AssertionError("Reviewed bridge sources changed during the regression run")

    def case(self, name):
        for variant in self.variants:
            with self.subTest(variant=variant):
                env = os.environ.copy()
                env["ASAN_OPTIONS"] = "detect_leaks=1:halt_on_error=1"
                env["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
                result = subprocess.run(
                    [str(self.root / variant), name], capture_output=True,
                    text=True, env=env, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                output = json.loads(result.stdout)
                self.assertEqual(output["case"], name)
                self.assertGreater(output["assertions"], 0)

    def test_both_raw_hopping_values_serialize_false_with_sized_parcel(self):
        self.case("raw-capabilities")

    def test_each_call_queries_driver_across_value_changes_and_failure_recovery(self):
        self.case("fresh-queries")

    def test_query_failures_never_serialize_success_even_with_true_output(self):
        self.case("query-errors")

    def test_status_allocation_and_each_parcel_failure_propagate(self):
        self.case("parcel-errors")

    def test_other_transactions_forward_original_arguments_and_status(self):
        self.case("forwarding")

    def test_exact_wonder_profile_and_descriptor_are_required_to_intercept(self):
        self.case("hook-boundaries")

    def test_original_registration_reuse_and_conflicting_null_or_missing_handlers(self):
        self.case("hook-registration")


if __name__ == "__main__":
    unittest.main(verbosity=2)
