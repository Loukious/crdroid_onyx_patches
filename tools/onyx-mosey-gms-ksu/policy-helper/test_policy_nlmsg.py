#!/usr/bin/env python3
"""Exercise the production helper against policy records it must preserve."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess


FIXTURE_SOURCE = r'''
#define main policy_helper_main
#include "policy_nlmsg.c"
#undef main

static void add_fixture(policydb_t *policy, avtab_key_t *key,
                        uint8_t selector, uint8_t driver,
                        uint32_t low, uint32_t high) {
    avtab_extended_perms_t x = {
        .specified = selector, .driver = driver,
        .perms = {low, 0, 0, 0, 0, 0, 0, high}
    };
    avtab_datum_t datum = {.data = 0, .xperms = &x};
    if (!avtab_insert_nonunique(&policy->te_avtab, key, &datum))
        die("fixture insert failed");
}

int main(int argc, char **argv) {
    if (argc != 4) return 2;
    size_t length;
    void *image = read_image(argv[1], &length);
    policydb_t policy;
    if (policydb_init(&policy) ||
        policydb_from_image(NULL, image, length, &policy))
        die("fixture input failed");
    uint32_t mask;
    avtab_key_t key = target_key(&policy, AVTAB_ALLOWED, &mask);
    avtab_datum_t *base = avtab_search(&policy.te_avtab, &key);
    if (!base) die("fixture base permission absent");
    base->data |= mask;
    key.specified = AVTAB_XPERMS_ALLOWED;
    if (!strcmp(argv[3], "split-complete")) {
        add_fixture(&policy, &key, AVTAB_XPERMS_NLMSG, 0, 1U << 18, 0);
        add_fixture(&policy, &key, AVTAB_XPERMS_NLMSG, 0, 1U << 19, 0);
        add_fixture(&policy, &key, AVTAB_XPERMS_NLMSG, 0, 1U << 28, 0);
        add_fixture(&policy, &key, AVTAB_XPERMS_NLMSG, 0, 1U << 29, 0);
        add_fixture(&policy, &key, AVTAB_XPERMS_NLMSG, 0, 1U << 30, 0);
    } else if (!strcmp(argv[3], "partial-with-unrelated")) {
        add_fixture(&policy, &key, AVTAB_XPERMS_NLMSG, 0,
                    (1U << 16) | (1U << 19), 1U << 31);
        add_fixture(&policy, &key, AVTAB_XPERMS_NLMSG, 1,
                    (1U << 18) | (1U << 28) | (1U << 29) | (1U << 30), 0);
        add_fixture(&policy, &key, AVTAB_XPERMS_IOCTLFUNCTION, 0,
                    (1U << 19) | (1U << 20), 0);
    } else if (!strcmp(argv[3], "getlink-only")) {
        add_fixture(&policy, &key, AVTAB_XPERMS_NLMSG, 0, 1U << 18, 0);
    } else if (!strcmp(argv[3], "getneigh-only")) {
        add_fixture(&policy, &key, AVTAB_XPERMS_NLMSG, 0, 1U << 30, 0);
    } else if (!strcmp(argv[3], "link-only") ||
               !strcmp(argv[3], "link-with-exact-ioctl")) {
        add_fixture(&policy, &key, AVTAB_XPERMS_NLMSG, 0,
                    (1U << 18) | (1U << 19), 0);
        if (!strcmp(argv[3], "link-with-exact-ioctl"))
            add_fixture(&policy, &key, AVTAB_XPERMS_IOCTLFUNCTION, 0,
                        1U << 19, 0);
    } else if (!strcmp(argv[3], "split-link-only")) {
        add_fixture(&policy, &key, AVTAB_XPERMS_NLMSG, 0, 1U << 18, 0);
        add_fixture(&policy, &key, AVTAB_XPERMS_NLMSG, 0, 1U << 19, 0);
    } else if (!strcmp(argv[3], "unrelated-ioctl")) {
        add_fixture(&policy, &key, AVTAB_XPERMS_IOCTLFUNCTION, 0,
                    (1U << 19) | (1U << 21), 0);
    } else {
        return 2;
    }
    void *output;
    size_t output_size;
    if (policydb_to_image(NULL, &policy, &output, &output_size))
        die("fixture serialization failed");
    write_output(argv[2], output, output_size);
    free(output);
    policydb_destroy(&policy);
    free(image);
    return 0;
}
'''


def run(argv):
    return subprocess.run([str(x) for x in argv], check=True, text=True,
                          capture_output=True).stdout.strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode(checkpolicy, policy, output):
    run([checkpolicy, "-b", "-C", "-M", "-c", "33", "-o", output, policy])
    return Counter(output.read_text().splitlines())


def rule(values):
    return f"(allowx mosey_server self (nlmsg netlink_route_socket (({values}))))"


def run_edge_tests(source, headers, host_lib, helper, checkpolicy, baseline, workdir):
    workdir.mkdir(parents=True, exist_ok=True)
    fixture_source = workdir / "fixture.c"
    fixture_source.write_text(FIXTURE_SOURCE)
    fixture = workdir / "fixture"
    compile_argv = ["cc", "-O2", "-Wall", "-Wextra", "-Werror",
                    "-I", source.parent, "-I", headers, fixture_source,
                    host_lib, "-pthread", "-o", fixture]
    run(compile_argv)
    full = rule("(range 0x12 0x13) (range 0x1c 0x1e)")
    pair = rule("(range 0x12 0x13)")
    expected = {
        "split-complete": ([], []),
        "partial-with-unrelated": (
            [rule("0x10 (range 0x12 0x13) (range 0x1c 0x1e) 0xff")],
            [rule("0x10 0x13 0xff")]),
        "getlink-only": ([full], [rule("0x12")]),
        "getneigh-only": ([full], [rule("0x1e")]),
        "link-only": ([full], [pair]),
        "link-with-exact-ioctl": ([full], [pair]),
        "split-link-only": None,
        "unrelated-ioctl": ([full], []),
    }
    results = {}
    for name, expected_delta in expected.items():
        original = workdir / f"{name}-before.bin"
        output = workdir / f"{name}-after.bin"
        repeat = workdir / f"{name}-repeat.bin"
        run([fixture, baseline, original, name])
        run([helper, original, output])
        before = decode(checkpolicy, original, workdir / f"{name}-before.cil")
        after = decode(checkpolicy, output, workdir / f"{name}-after.cil")
        added, removed = after - before, before - after
        # Either split record may hold the added bits. Exactly one of these
        # two deltas is allowed; the other record and all unrelated rows survive.
        if name == "split-link-only":
            permitted_deltas = [([rule(f"{bit} (range 0x1c 0x1e)")], [rule(bit)])
                                for bit in ("0x12", "0x13")]
        else:
            permitted_deltas = [expected_delta]
        if not any(added == Counter(a) and removed == Counter(r)
                   for a, r in permitted_deltas):
            raise RuntimeError(f"{name} changed unrelated records: "
                               f"added={list(added.elements())}; removed={list(removed.elements())}")
        if name == "split-complete" and original.read_bytes() != output.read_bytes():
            raise RuntimeError("split complete NLMSG grant was needlessly rewritten")
        run([helper, output, repeat])
        if repeat.read_bytes() != output.read_bytes():
            raise RuntimeError(f"{name} was not byte-idempotent")
        results[name] = {"passed": True, "input_sha256": sha(original),
                         "output_sha256": sha(output), "byte_idempotent": True,
                         "added": list(added.elements()), "removed": list(removed.elements()),
                         "records_compared": sum(before.values())}
    return {"passed": True, "scenario_count": len(results), "scenarios": results,
            "fixture_source_sha256": sha(fixture_source),
            "fixture_compile_argv": [str(x) for x in compile_argv]}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("source", "headers", "host-lib", "helper", "checkpolicy",
                     "baseline", "workdir"):
        parser.add_argument("--" + argument, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_edge_tests(args.source, args.headers, args.host_lib,
                                   args.helper, args.checkpolicy, args.baseline,
                                   args.workdir), indent=2))
