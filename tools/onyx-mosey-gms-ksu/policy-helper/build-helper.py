#!/usr/bin/env python3
"""Build the scoped ARM64 helper and verify its policy deltas offline."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import subprocess
from test_policy_nlmsg import run_edge_tests


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(argv):
    result = subprocess.run([str(x) for x in argv], check=True,
                            text=True, capture_output=True)
    return result.stdout.strip()


def header_digest(root):
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.h")):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def decode(checkpolicy, policy, output):
    run([checkpolicy, "-b", "-C", "-M", "-c", "33", "-o", output, policy])
    return Counter(output.read_text().splitlines())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--ndk", type=Path, required=True)
    parser.add_argument("--baseline-policy", type=Path, required=True)
    parser.add_argument("--ksud-policy", type=Path, required=True)
    parser.add_argument("--loaded-policy", type=Path,
                        help="Saved SETLINK-only kernel policy to test the full message upgrade")
    parser.add_argument("--link-policy", type=Path,
                        help="Saved GETLINK/SETLINK kernel policy to test adding neighbor messages")
    parser.add_argument("--getneigh-policy", type=Path,
                        help="Saved GETLINK/SETLINK/GETNEIGH policy to test adding NEWNEIGH/DELNEIGH")
    parser.add_argument("--newneigh-policy", type=Path,
                        help="Saved GETLINK/SETLINK/NEWNEIGH/GETNEIGH policy to test adding only DELNEIGH")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    args = parser.parse_args()
    source = Path(__file__).with_name("policy_nlmsg.c")
    headers = args.rom / "external/selinux/libsepol/include"
    libs = args.rom / "out/soong/.intermediates/external/selinux/libsepol/libsepol"
    android_lib = libs / "android_arm64_armv8-2a-dotprod_static/libsepol.a"
    host_lib = libs / "linux_glibc_x86_64_static/libsepol.a"
    clang = args.rom / "prebuilts/clang/host/linux-x86/clang-r596125/bin/clang"
    checkpolicy = args.rom / "out/host/linux-x86/bin/checkpolicy"
    sysroot = args.ndk / "toolchains/llvm/prebuilt/linux-x86_64/sysroot"
    for path in [source, android_lib, host_lib, clang, checkpolicy,
                 sysroot, args.baseline_policy, args.ksud_policy,
                 *[p for p in (args.loaded_policy, args.link_policy,
                               args.getneigh_policy, args.newneigh_policy) if p is not None]]:
        if not path.exists():
            parser.error(f"required input is missing: {path}")
    args.workdir.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    common = ["-O2", "-Wall", "-Wextra", "-Werror", "-I", headers, source]
    arm_command = [clang, "--target=aarch64-linux-android35",
                   f"--sysroot={sysroot}", "-fPIE", "-pie",
                   "-ffunction-sections", "-fdata-sections",
                   "-Wl,--gc-sections", "-Wl,--build-id=sha1",
                   "-Wl,-z,max-page-size=16384", "-Wl,-z,common-page-size=16384",
                   *common, android_lib, "-llog", "-pthread", "-o", args.output]
    run(arm_command)
    elf = args.output.read_bytes()
    if (elf[:6] != b"\x7fELF\x02\x01" or len(elf) < 64 or
            struct.unpack_from("<HH", elf, 16) != (3, 183)):
        raise RuntimeError("output is not an ARM64 PIE ELF")
    phoff = struct.unpack_from("<Q", elf, 32)[0]
    phsize, phcount = struct.unpack_from("<HH", elf, 54)
    if phsize != 56 or not phcount or phoff + phsize * phcount > len(elf):
        raise RuntimeError("output has invalid ELF program headers")
    load_segments = []
    for index in range(phcount):
        kind, _, offset, virtual, _, _, _, alignment = struct.unpack_from(
            "<IIQQQQQQ", elf, phoff + index * phsize)
        if kind == 1:
            if alignment < 16384 or (offset - virtual) % 16384:
                raise RuntimeError("output needs Android 16 KiB LOAD alignment")
            load_segments.append({"offset": offset, "virtual": virtual,
                                  "alignment": alignment})
    if not load_segments:
        raise RuntimeError("output has no LOAD segments")
    host = args.workdir / "onyx-mosey-nlmsg-host"
    run(["cc", *common, host_lib, "-pthread", "-o", host])

    old_nlmsg = "(allowx mosey_server self (nlmsg netlink_route_socket ((0x13))))"
    link_nlmsg = old_nlmsg.replace("0x13", "(range 0x12 0x13)")
    getneigh_nlmsg = old_nlmsg.replace("0x13", "(range 0x12 0x13) 0x1e")
    newneigh_nlmsg = old_nlmsg.replace("0x13", "(range 0x12 0x13) 0x1c 0x1e")
    nlmsg = old_nlmsg.replace("0x13", "(range 0x12 0x13) (range 0x1c 0x1e)")
    ioctl = "(allowx mosey_server self (ioctl netlink_route_socket ((0x13))))"
    tests = {}
    decoded = {}
    outputs = {}
    for name, path in [("baseline", args.baseline_policy), ("ksud", args.ksud_policy)]:
        output = args.workdir / f"{name}-patched.bin"
        run([host, path, output])
        before = decode(checkpolicy, path, args.workdir / f"{name}-before.cil")
        after = decode(checkpolicy, output, args.workdir / f"{name}-after.cil")
        added, removed = list((after - before).elements()), list((before - after).elements())
        if name == "ksud":
            if added != [nlmsg] or removed != [ioctl]:
                raise RuntimeError("selector repair changed unrelated policy records")
        else:
            base_add = [x for x in added if x.startswith("(allow mosey_server self ")]
            if (len(added) != 2 or len(removed) != 1 or nlmsg not in added or
                    len(base_add) != 1 or
                    removed[0].replace("nlmsg_getneigh)))", "nlmsg_getneigh nlmsg)))")
                    != base_add[0]):
                raise RuntimeError("baseline repair changed unrelated policy records")
        tests[name] = {"passed": True, "input_sha256": sha(path),
                       "output_sha256": sha(output), "added": added, "removed": removed,
                       "records_compared": sum(before.values())}
        decoded[name] = before
        outputs[name] = output
    for name, path, previous in (("loaded", args.loaded_policy, old_nlmsg),
                                 ("link", args.link_policy, link_nlmsg),
                                 ("getneigh", args.getneigh_policy, getneigh_nlmsg),
                                 ("newneigh", args.newneigh_policy, newneigh_nlmsg)):
        if path is None:
            continue
        output = args.workdir / f"{name}-patched.bin"
        run([host, path, output])
        loaded = decode(checkpolicy, path, args.workdir / f"{name}-before.cil")
        after = decode(checkpolicy, output, args.workdir / f"{name}-after.cil")
        added = list((after - loaded).elements())
        removed = list((loaded - after).elements())
        if added != [nlmsg] or removed != [previous]:
            raise RuntimeError(f"{name} upgrade changed unrelated loaded policy records")
        tests[f"{name}_kernel_policy"] = {"passed": True,
            "input_sha256": sha(path), "output_sha256": sha(output),
            "offline_upgrade": True, "added": added, "removed": removed,
            "records_compared": sum(loaded.values())}
        outputs[name] = output
    repeats = {}
    for name, output in outputs.items():
        repeat = args.workdir / f"{name}-idempotent.bin"
        run([host, output, repeat])
        if repeat.read_bytes() != output.read_bytes():
            raise RuntimeError(f"repeat changed an already-correct {name} policy")
        repeats[name] = {"passed": True, "byte_identical": True,
                         "input_sha256": sha(output), "repeat_sha256": sha(repeat)}
    tests["idempotence"] = {"passed": True, "byte_identical": True, "inputs": repeats}
    tests["edge_preservation"] = run_edge_tests(
        source, headers, host_lib, host, checkpolicy, args.baseline_policy,
        args.workdir / "edge-tests")
    receipt = {
        "passed": True, "helper_sha256": sha(args.output),
        "helper_size": args.output.stat().st_size, "architecture": "aarch64",
        "elf_type": "ET_DYN", "load_segments": load_segments,
        "android_16k_load_alignment_passed": True,
        "android_api": 35, "source_sha256": sha(source),
        "build_script_sha256": sha(Path(__file__)),
        "test_script_sha256": sha(Path(__file__).with_name("test_policy_nlmsg.py")),
        "netlink_messages": {"RTM_GETLINK": 18, "RTM_SETLINK": 19,
                             "RTM_NEWNEIGH": 28, "RTM_DELNEIGH": 29, "RTM_GETNEIGH": 30},
        "libsepol_android_sha256": sha(android_lib),
        "libsepol_host_sha256": sha(host_lib),
        "libsepol_headers_sha256": header_digest(headers),
        "selinux_source_revision": run(["git", "-C", args.rom / "external/selinux",
                                         "rev-parse", "HEAD"]),
        "compiler_version": run([clang, "--version"]),
        "compiler_sha256": sha(clang),
        "compile_argv": [str(x) for x in arm_command], "tests": tests,
        "limits": "Offline target ELF build and semantic tests; module --apply still requires a root device execution check."
    }
    args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"passed": True, "helper_sha256": receipt["helper_sha256"],
                      "receipt": str(args.receipt)}, indent=2))


if __name__ == "__main__":
    main()
