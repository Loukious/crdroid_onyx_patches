#!/usr/bin/env python3
"""Compile the complete DT2S controller against host input and main-loop models.

Usage: python3 -B ci/check-dt2s-shade.py /isolated/DoubleTapToSleepController.java --out DIR
The production file is compiled unchanged. These tests check controller behavior,
not Android's native input stack, Dagger graph, or physical gesture recognition.
"""
import argparse
import contextlib
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        parser.error("a host JDK is required (javac and java)")
    spec = importlib.util.spec_from_file_location(
        "dt2s_models", ROOT / "tests/dt2s_host_models.py")
    models = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(models)
    source = args.source.read_bytes()
    with contextlib.ExitStack() as stack:
        output = args.out or Path(stack.enter_context(
            tempfile.TemporaryDirectory(prefix="onyx-dt2s-shade-")))
        sources, classes = output / "src", output / "classes"
        classes.mkdir(parents=True, exist_ok=True)
        for name, body in models.SOURCES.items():
            path = sources / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
        production = sources / "com/android/systemui/dt2s/DoubleTapToSleepController.java"
        production.parent.mkdir(parents=True, exist_ok=True)
        production.write_bytes(source)
        harness = sources / "DoubleTapToSleepControllerHarness.java"
        shutil.copyfile(ROOT / "tests/DoubleTapToSleepControllerHarness.java", harness)
        files = sorted(str(p) for p in sources.rglob("*.java"))
        built = subprocess.run(
            [javac, "--release", "17", "-Xlint:unchecked", "-Werror", "-d", str(classes), *files],
            capture_output=True, text=True, timeout=45)
        (output / "compile.log").write_text(built.stdout + built.stderr)
        if built.returncode:
            raise RuntimeError(f"controller compilation failed:\n{built.stdout}{built.stderr}")
        result = subprocess.run(
            [java, "-ea", "-cp", str(classes), "DoubleTapToSleepControllerHarness"],
            capture_output=True, text=True, timeout=15)
        (output / "run.log").write_text(result.stdout + result.stderr)
        counts = re.search(r"passed=(\d+) failed=(\d+)", result.stdout)
        report = {
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "javac": javac,
            "exit": result.returncode,
            "passed": int(counts[1]) if counts else None,
            "failed": int(counts[2]) if counts else None,
        }
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(result.stdout + result.stderr, end="")
        return int(result.returncode != 0 or counts is None)


if __name__ == "__main__":
    raise SystemExit(main())
