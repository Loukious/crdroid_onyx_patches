#!/usr/bin/env python3
"""Run the complete bouncer transition interactor with real host coroutines.

Requires a Kotlin compiler distribution with kotlinx-coroutines-core-jvm.jar.
The production source is copied unchanged; Android services are host models.
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
    parser.add_argument("--kotlin-home", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    kotlin = args.kotlin_home.resolve()
    compiler = kotlin / "bin/kotlinc"
    coroutines = kotlin / "lib/kotlinx-coroutines-core-jvm.jar"
    java = shutil.which("java")
    if not compiler.is_file() or not coroutines.is_file() or not java:
        parser.error("a JDK and Kotlin distribution with coroutines are required")
    spec = importlib.util.spec_from_file_location(
        "bouncer_models", ROOT / "tests/bouncer_back_host_models.py")
    models = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(models)
    source = args.source.read_bytes()
    with contextlib.ExitStack() as stack:
        output = (args.out or Path(stack.enter_context(
            tempfile.TemporaryDirectory(prefix="onyx-bouncer-back-")))).resolve()
        sources = output / "src"
        for name, body in models.SOURCES.items():
            path = sources / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
        production = sources / (
            "com/android/systemui/keyguard/domain/interactor/"
            "FromLockscreenTransitionInteractor.kt")
        production.write_bytes(source)
        shutil.copyfile(ROOT / "tests/LegacyBouncerBackHarness.kt",
                        sources / "LegacyBouncerBackHarness.kt")
        jar = output / "regression.jar"
        files = sorted(str(p) for p in sources.rglob("*.kt"))
        built = subprocess.run(
            [str(compiler), "-J-Xmx512m", "-jvm-target", "17",
             "-cp", str(coroutines), "-include-runtime", "-d", str(jar), *files],
            capture_output=True, text=True, timeout=90)
        (output / "compile.log").write_text(built.stdout + built.stderr)
        if built.returncode:
            raise RuntimeError(f"compilation failed:\n{built.stdout}{built.stderr}")
        result = subprocess.run(
            [java, "-ea", "-cp", f"{jar}:{coroutines}", "LegacyBouncerBackHarnessKt"],
            capture_output=True, text=True, timeout=15)
        (output / "run.log").write_text(result.stdout + result.stderr)
        counts = re.search(r"passed=(\d+) failed=(\d+)", result.stdout)
        report = {
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "exit": result.returncode,
            "passed": int(counts[1]) if counts else None,
            "failed": int(counts[2]) if counts else None,
        }
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(result.stdout + result.stderr, end="")
        return int(result.returncode != 0 or counts is None)


if __name__ == "__main__":
    raise SystemExit(main())
