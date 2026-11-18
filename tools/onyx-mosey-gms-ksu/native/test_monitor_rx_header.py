#!/usr/bin/env python3
"""Check production monitor publication before the AF_PACKET RAW receive tap.

Run with --source-root pointing at kernel/platform/kernel-6.18 (containing
common/ and modules/). The retained unfixed production callback must reproduce
the original signed skb_under_panic values; the current callback must preserve
packet payloads, initialize metadata, and retain every existing publication
route. All compilation and execution are offline, with ASan and UBSan.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "tests/monitor_rx_header.c"
BASELINE = HERE / "tests/monitor_rx_header_unfixed.c"
SOURCE_FILES = {
    "callback": "modules/qcacld-3.0/components/dp/core/src/wlan_dp_txrx.c",
    "headers": "common/include/linux/skbuff.h",
    "packet": "common/net/packet/af_packet.c",
    "qdf": "modules/qca-wifi-host-cmn/qdf/linux/src/i_qdf_nbuf.h",
    "enum": "modules/qcacld-3.0/components/dp/dispatcher/inc/wlan_dp_public_struct.h",
}
EXPECTED_PANIC = (
    "AF_PACKET_UNDERFLOW put=-65329 len=-64934 data_offset=206 "
    "mac_header=65535 tail=280 end=384"
)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def extract_function(source, name):
    """Keep the complete C definition, ignoring braces in comments/literals."""
    protected = re.compile(
        r'/\*[\s\S]*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''
    )
    masked = protected.sub(
        lambda match: re.sub(r"[^\n]", " ", match.group()), source
    )
    match = re.search(
        r"(?m)^[\w\s*]+\b" + re.escape(name) + r"\([^;{}]*\)\s*\{", masked
    )
    if match is None:
        raise ValueError("Production function not found: " + name)
    start = match.start()
    while masked[start].isspace():
        start += 1
    opening = masked.index("{", start)
    depth = 0
    for token in re.compile(r"[{}]").finditer(masked, opening):
        if token.group() == "{":
            depth += 1
        elif token.group() == "}":
            depth -= 1
            if depth == 0:
                return source[start:token.end()]
    raise ValueError("Unclosed production function: " + name)


def generate(source, inputs):
    capture = extract_function(inputs["packet"], "tpacket_rcv")
    begin = capture.index("\tif (dev_has_header(dev)) {")
    end = capture.index("\n\tsnaplen =", begin)
    push_enum = re.search(
        r"enum dp_nbuf_push_type \{.*?\n\};", inputs["enum"], re.S
    )
    require(push_enum is not None, "Production push enum not found")
    replacements = {
        "PUSH_ENUM": push_enum.group(),
        "HEADER_HELPERS": "\n".join(
            extract_function(inputs["headers"], name)
            for name in (
                "skb_mac_header_was_set", "skb_mac_header", "skb_reset_mac_header",
                "skb_network_header", "skb_network_offset",
            )
        ) + "\n" + extract_function(inputs["qdf"], "__qdf_nbuf_set_protocol"),
        "CAPTURE_BRANCH": capture[begin:end],
        "CALLBACK": "\n".join(
            extract_function(source, name)
            for name in ("dp_mon_rx_push_type", "dp_mon_rx_packet_cbk")
        ),
    }
    code = FIXTURE.read_text()
    for marker, body in replacements.items():
        placeholder = "/* INSERT_" + marker + " */"
        require(code.count(placeholder) == 1, "Missing/duplicate fixture marker: " + marker)
        code = code.replace(placeholder, body)
    require("/* INSERT_" not in code, "Unexpanded fixture marker")
    return code


def run(source, label, feature, inputs, directory, compiler):
    basename = label + ("-wonder" if feature else "-no-wonder")
    code = generate(source, inputs)
    path = directory / (basename + ".c")
    executable = directory / basename
    path.write_text(code)
    command = [
        *compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
        "-Wno-unused-parameter", "-Wno-unused-function",
        "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
        "-fno-pie", "-no-pie",
    ]
    if feature:
        command.append("-DFEATURE_WLAN_WONDER")
    command.extend((str(path), "-o", str(executable)))
    compiled = subprocess.run(command, capture_output=True, text=True, timeout=60)
    require(compiled.returncode == 0, "Compilation failed:\n" + compiled.stderr)
    result = subprocess.run(
        [str(executable)], capture_output=True, text=True, timeout=30
    )
    return {
        "label": label, "wonder_feature": feature, "returncode": result.returncode,
        "stdout": result.stdout.strip(), "stderr": result.stderr.strip(),
        "generated_sha256": hashlib.sha256(code.encode()).hexdigest(),
    }


def verify(source_root, compiler):
    source_root = Path(source_root).resolve()
    paths = {key: source_root / value for key, value in SOURCE_FILES.items()}
    inputs = {key: path.read_text() for key, path in paths.items()}
    before = BASELINE.read_text()
    results = []
    with tempfile.TemporaryDirectory(prefix="onyx-monitor-rx-header-") as temporary:
        directory = Path(temporary)
        for feature in (True, False):
            control = run(before, "unfixed-control", feature, inputs, directory, compiler)
            require(control["returncode"] == 42, control)
            require(control["stderr"] == EXPECTED_PANIC and not control["stdout"], control)
            fixed = run(inputs["callback"], "fixed", feature, inputs, directory, compiler)
            require(fixed["returncode"] == 0 and not fixed["stderr"], fixed)
            fixed["metrics"] = json.loads(fixed["stdout"])
            results.extend((control, fixed))
    return {
        "status": "PASS", "sanitizers": "ASan+UBSan", "compiler": compiler,
        "source_root": str(source_root),
        "scope": (
            "Actual dp_mon_rx_packet_cbk/dp_mon_rx_push_type, common header helpers, "
            "QDF protocol assignment, and AF_PACKET tpacket_rcv header-adjustment block."
        ),
        "negative_control": (
            "Retained unfixed production functions reproduce put=-65329 len=-64934 "
            "with MAC header 65535 and data offset 206 in both feature variants."
        ),
        "coverage": [
            "Wonder feature enabled/disabled",
            "Owned/ordinary monitor and atomic/process publication routes",
            "Single/2/3 packet chains and refused publication counters",
            "Unset/stale/valid MAC offsets and protocol initialization",
            "Logical non-linear SKB with preserved linear and fragment bytes",
            "Null context/buffer/interface and transport-not-ready rejection",
        ],
        "source_sha256": {
            SOURCE_FILES[key]: hashlib.sha256(path.read_bytes()).hexdigest()
            for key, path in paths.items()
        },
        "test_sha256": {
            str(path.relative_to(HERE)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (Path(__file__).resolve(), FIXTURE, BASELINE)
        },
        "results": results,
        "limits": [
            "Host fixture uses SKB/queue/stats mocks and guards skb_push before unsafe pointer mutation.",
            "The whole driver build, firmware reception, device discovery, and file transfer require separate validation.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root", type=Path, required=True,
        help="Kernel source root containing common/ and modules/",
    )
    parser.add_argument("--cc", default=os.environ.get("CC", "cc"), help="Host C compiler command")
    parser.add_argument("--receipt", type=Path, help="Optional JSON output path")
    args = parser.parse_args()
    compiler = shlex.split(args.cc)
    if not compiler:
        parser.error("--cc must name a compiler")
    receipt = json.dumps(verify(args.source_root, compiler), indent=2) + "\n"
    if args.receipt:
        args.receipt.write_text(receipt)
    print(receipt, end="")


if __name__ == "__main__":
    main()
