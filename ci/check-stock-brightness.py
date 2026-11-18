#!/usr/bin/env python3
"""Run actual Onyx lux/ramp code and JUnit tests on the host.

Android service registration, framework resources and physical panel/sensor output
need separate Android build/device validation. Ramp stubs model the Android APIs;
Spline and BrightnessUtils are compiled directly from the supplied ROM tree.
"""

import argparse
import contextlib
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET


HERE = Path(__file__).resolve().parent
JAVA_DISPLAY = Path("frameworks/base/services/core/java/com/android/server/display")
JAVA_TESTS = Path("frameworks/base/services/tests/displayservicetests/src/com/android/server/display")


def verify_profile(rom):
    evidence = HERE.parent / "notes/stock-brightness-evidence"
    profile = json.loads((evidence / "stock-profile.json").read_text())
    overlay = ET.parse(rom / "device/xiaomi/onyx/overlay/FrameworkOverlayOnyx/res/values/config.xml")
    lux = [0.0, *(float(item.text) for item in overlay.findall(
        ".//integer-array[@name='config_autoBrightnessLevels']/item"))]
    nits = [float(item.text) for item in overlay.findall(
        ".//array[@name='config_autoBrightnessDisplayValuesNits']/item")]
    with (evidence / "default-lux-nits.csv").open(newline="") as stream:
        expected = [(float(row["lux"]), float(row["nits"])) for row in csv.DictReader(stream)]
    if len(lux) != len(nits) or list(zip(lux, nits)) != expected:
        raise ValueError("Onyx default lux/nits calibration differs from the retained stock table")
    source = (rom / JAVA_DISPLAY / "OnyxLuxPolicy.java").read_text()
    for constant, key in (("STOCK_BRIGHT_LUX", "bright_lux"), ("STOCK_BRIGHT", "bright_threshold"),
                          ("STOCK_DARK_LUX", "dark_lux"), ("STOCK_DARK", "dark_threshold")):
        match = re.search(r"\b" + constant + r"\s*=\s*\{([^}]*)\}", source)
        if match is None:
            raise ValueError(f"missing stock threshold array: {constant}")
        actual = [float(value.strip().removesuffix("f")) for value in match[1].split(",")]
        if actual != profile["hysteresis"][key]:
            raise ValueError(f"{constant} differs from the retained stock threshold resources")
    for panel_id in profile["panel_ids"]:
        panel = ET.parse(rom / "vendor/xiaomi/onyx/proprietary/vendor/etc/displayconfig"
                         / f"display_id_{panel_id}.xml")
        if panel.find("screenBrightnessMap").get("interpolation") != "linear":
            raise ValueError(f"panel {panel_id} does not request stock linear nits conversion")
        for kind, key in (("Fast", "fast_float"), ("Slow", "slow_float")):
            for direction in ("Increase", "Decrease"):
                actual = float(panel.findtext(f"screenBrightnessRamp{kind}{direction}"))
                if abs(actual - profile["fallback_ramp"][key]) > 1e-10:
                    raise ValueError(f"panel {panel_id} has incorrect {kind}/{direction} fallback ramp")
    return {"default_curve_points": len(expected), "threshold_anchors": 34,
            "panel_configs": len(profile["panel_ids"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--suite", choices=("all", "lux", "ramp"), default="all")
    args = parser.parse_args()
    rom = args.rom.resolve()
    compiler, runtime = shutil.which("javac"), shutil.which("java")
    if not compiler or not runtime:
        parser.error("javac and java are required")
    jars = [rom / "prebuilts/devtools/tools/lib" / name for name in
            ("junit-4.12.jar", "hamcrest-core-1.3.jar")]
    if not all(p.is_file() for p in jars):
        parser.error("ROM must provide prebuilts/devtools/tools/lib JUnit and Hamcrest jars")
    suites = {
        "lux": ([rom / JAVA_DISPLAY / "OnyxLuxPolicy.java",
                 rom / JAVA_TESTS / "OnyxLuxPolicyTest.java",
                 rom / JAVA_TESTS / "OnyxBrightnessSensorSampleTimeTest.java"],
                ["com.android.server.display.OnyxLuxPolicyTest",
                 "com.android.server.display.OnyxBrightnessSensorSampleTimeTest"]),
        "ramp": ([*sorted((HERE / "brightness/ramp-stubs").rglob("*.java")),
                  rom / "frameworks/base/core/java/android/util/Spline.java",
                  rom / "frameworks/base/core/java/com/android/internal/display/BrightnessUtils.java",
                  rom / JAVA_DISPLAY / "OnyxBrightnessRampController.java",
                  rom / JAVA_DISPLAY / "RampAnimator.java",
                  rom / JAVA_TESTS / "OnyxBrightnessRampControllerTest.java",
                  rom / JAVA_TESTS / "RampAnimatorTest.java"],
                 ["com.android.server.display.OnyxBrightnessRampControllerTest",
                  "com.android.server.display.RampAnimatorTest"]),
    }
    selected = suites if args.suite == "all" else {args.suite: suites[args.suite]}
    with contextlib.ExitStack() as stack:
        output = args.out or Path(stack.enter_context(
            tempfile.TemporaryDirectory(prefix="onyx-stock-brightness-")))
        output.mkdir(parents=True, exist_ok=True)
        report = {"rom": str(rom), "scope": "stock profile and host lux/ramp tests",
                  "profile": verify_profile(rom), "suites": {}}
        print(f"stock profile: {report['profile']}")
        for name, (sources, tests) in selected.items():
            classes = output / name / "classes"
            if classes.exists():
                shutil.rmtree(classes)
            classes.mkdir(parents=True)
            command = [compiler, "-cp", str(jars[0]), "-d", str(classes),
                       *(str(p) for p in sources)]
            compiled = subprocess.run(command, capture_output=True, text=True, timeout=90)
            (output / name / "compile.log").write_text(compiled.stdout + compiled.stderr)
            if compiled.returncode:
                raise RuntimeError(f"{name} compilation failed:\n{compiled.stdout}{compiled.stderr}")
            executed = subprocess.run(
                [runtime, "-cp", ":".join(str(p) for p in (classes, *jars)),
                 "org.junit.runner.JUnitCore", *tests],
                capture_output=True, text=True, timeout=90)
            (output / name / "run.log").write_text(executed.stdout + executed.stderr)
            print(f"{name}:\n{executed.stdout}{executed.stderr}", end="")
            report["suites"][name] = {
                "exit": executed.returncode,
                "sources": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
            }
            if executed.returncode:
                (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
                return executed.returncode
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
