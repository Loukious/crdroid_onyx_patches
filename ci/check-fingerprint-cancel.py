#!/usr/bin/env python3
"""Compile the real cancellation/notification methods against host HAL models.

Usage: python3 -B ci/check-fingerprint-cancel.py /isolated/Session.cpp --out DIR
No Soong invocation, live source edit, device action or biometric data is needed.
Both legacy ABI branches are compiled. This checks callback behavior, not the
Android service's complete ABI or actual fingerprint matching.
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
spec = importlib.util.spec_from_file_location("source_tools", ROOT / "upstream_fix_state.py")
source_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source_tools)


def extract(source, pattern):
    code = source_tools.code_only(source)
    matches = list(re.finditer(pattern, code))
    if len(matches) != 1:
        raise ValueError(f"expected one production method: {pattern}")
    match = matches[0]
    opening = code.index("{", match.start())
    return source[match.start():source_tools.block_end(code, opening)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--cxx", default="c++")
    args = parser.parse_args()
    compiler = shutil.which(args.cxx)
    if compiler is None:
        parser.error("a host C++ compiler is required (--cxx)")
    source = args.source.read_text()
    methods = [extract(source, pattern) for pattern in (
        r"ndk::ScopedAStatus\s+Session::cancel\s*\(",
        r"Error\s+Session::VendorErrorFilter\s*\(",
        r"void\s+Session::notify\s*\(",
    )]
    template = (ROOT / "tests/fingerprint_cancel_harness.cpp").read_text()
    marker = "// PRODUCTION_METHODS"
    if template.count(marker) != 1:
        raise ValueError("missing or duplicate production-method insertion point")
    generated = template.replace(marker, "\n\n".join(methods))
    with contextlib.ExitStack() as stack:
        output = args.out or Path(stack.enter_context(
            tempfile.TemporaryDirectory(prefix="onyx-fingerprint-cancel-")))
        output.mkdir(parents=True, exist_ok=True)
        cpp = output / "fingerprint_cancel.cpp"
        cpp.write_text(generated)
        report = {
            "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "method_sha256": [hashlib.sha256(m.encode()).hexdigest() for m in methods],
            "compiler": compiler,
            "variants": {},
        }
        failed = False
        for variant, defines in (("legacy", []), ("v2", ["-DIMPL_V2"])):
            executable = output / ("fingerprint_cancel_" + variant)
            command = [compiler, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror",
                       "-fsanitize=undefined", "-fno-sanitize-recover=undefined",
                       *defines, str(cpp), "-o", str(executable)]
            built = subprocess.run(command, capture_output=True, text=True, timeout=45)
            (output / (variant + "-compile.log")).write_text(built.stdout + built.stderr)
            if built.returncode:
                raise RuntimeError(f"{variant} compilation failed:\n{built.stdout}{built.stderr}")
            run = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
            (output / (variant + "-run.log")).write_text(run.stdout + run.stderr)
            counts = re.search(r"passed=(\d+) failed=(\d+)", run.stdout)
            report["variants"][variant] = {
                "exit": run.returncode,
                "passed": int(counts[1]) if counts else None,
                "failed": int(counts[2]) if counts else None,
            }
            print(f"{variant}:\n{run.stdout}{run.stderr}", end="")
            failed |= run.returncode != 0 or counts is None
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
