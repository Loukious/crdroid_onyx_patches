#!/usr/bin/env python3
"""Build the Onyx Mosey flag/boot helper and optional validated native adapter."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zipfile

HERE = Path(__file__).resolve().parent


def validate_native(native_library, native_clearance):
    proof = json.loads(native_clearance.read_text())
    data = native_library.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if (proof.get("passed") is not True or proof.get("native_sha256") != digest or
            proof.get("mosey_domain_query4_passed") is not True or
            proof.get("selinux_enforcing") is not True):
        raise ValueError("Native adapter must match its successful Mosey-domain validation")
    sources = HERE.parents[1] / "assets/onyx-mosey-source/files"
    expected = {name: hashlib.sha256((sources / name).read_bytes()).hexdigest()
                for name in ("config.c", "config.map", "wonder-cap-query.c",
                             "wonder-cap-query.h", "wonder-capability-bridge.c")}
    if proof.get("source_sha256") != expected:
        raise ValueError("Native adapter sources differ from the validated build")
    if (data[:6] != b"\x7fELF\x02\x01" or len(data) < 64 or
            struct.unpack_from("<HH", data, 16) != (3, 183)):
        raise ValueError("Native adapter must be an ARM64 shared library")
    phoff = struct.unpack_from("<Q", data, 32)[0]
    phsize, phcount = struct.unpack_from("<HH", data, 54)
    if phsize != 56 or not phcount or phoff + phsize * phcount > len(data):
        raise ValueError("Native adapter has invalid ELF program headers")
    for index in range(phcount):
        kind, _, offset, virtual, _, _, _, alignment = struct.unpack_from("<IIQQQQQQ", data, phoff + index * phsize)
        if kind == 1 and (alignment < 16384 or (offset - virtual) % 16384):
            raise ValueError("Native adapter needs Android 16 KiB LOAD alignment")
    return data, proof


def validate_cache(helper, clearance):
    proof = json.loads(clearance.read_text())
    data = helper.read_bytes()
    expected_sources = {
        name: hashlib.sha256((HERE / "native" / name).read_bytes()).hexdigest()
        for name in ("cache-overlay.cpp", "snapshot-contract.h")
    }
    if (proof.get("passed") is not True or
            proof.get("helper_sha256") != hashlib.sha256(data).hexdigest() or
            proof.get("source_sha256") != expected_sources or
            proof.get("architecture") != "aarch64"):
        raise ValueError("Cache helper must match its validated ARM64 build and source contract")
    tests = proof.get("tests")
    if not isinstance(tests, dict) or not tests or any(
            not isinstance(result, dict) or result.get("passed") is not True
            for result in tests.values()):
        raise ValueError("Cache helper requires passing preservation and rollback tests")
    if (data[:6] != b"\x7fELF\x02\x01" or len(data) < 64 or
            struct.unpack_from("<HH", data, 16) != (3, 183)):
        raise ValueError("Cache helper must be an ARM64 PIE executable")
    phoff = struct.unpack_from("<Q", data, 32)[0]
    phsize, phcount = struct.unpack_from("<HH", data, 54)
    if phsize != 56 or not phcount or phoff + phsize * phcount > len(data):
        raise ValueError("Cache helper has invalid ELF program headers")
    for index in range(phcount):
        kind, _, offset, virtual, _, _, _, alignment = struct.unpack_from(
            "<IIQQQQQQ", data, phoff + index * phsize)
        if kind == 1 and (alignment < 16384 or (offset - virtual) % 16384):
            raise ValueError("Cache helper needs Android 16 KiB LOAD alignment")
    return data, proof


def build(output, helper, clearance, native_library=None, native_clearance=None,
          cache_helper=None, cache_clearance=None):
    proof = json.loads(clearance.read_text())
    data = helper.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if proof.get("passed") is not True or proof.get("helper_sha256") != digest:
        raise ValueError("Policy helper must match its successful validation receipt")
    if proof.get("source_sha256") != hashlib.sha256((HERE / "policy-helper/policy_nlmsg.c").read_bytes()).hexdigest():
        raise ValueError("Policy helper source differs from the validated build")
    if proof.get("architecture") != "aarch64" or data[:5] != b"\x7fELF\x02" or struct.unpack_from("<H", data, 18)[0] != 183:
        raise ValueError("Policy helper must be the verified ARM64 ELF")
    phoff = struct.unpack_from("<Q", data, 32)[0]
    phsize, phcount = struct.unpack_from("<HH", data, 54)
    for index in range(phcount):
        kind, _, offset, virtual, _, _, _, alignment = struct.unpack_from("<IIQQQQQQ", data, phoff + index * phsize)
        if kind == 1 and (alignment < 16384 or (offset - virtual) % 16384):
            raise ValueError("Policy helper needs Android 16 KiB LOAD alignment")
    output.parent.mkdir(parents=True, exist_ok=True)
    if (native_library is None) != (native_clearance is None):
        raise ValueError("Native library and validation receipt must be supplied together")
    if (cache_helper is None) != (cache_clearance is None):
        raise ValueError("Cache helper and validation receipt must be supplied together")
    if cache_helper is None:
        raise ValueError("Module requires the validated shared-cache helper")
    native_data = None
    native_proof = None
    if native_library is not None:
        native_data, native_proof = validate_native(native_library, native_clearance)
    cache_data = None
    cache_proof = None
    if cache_helper is not None:
        cache_data, cache_proof = validate_cache(cache_helper, cache_clearance)
    flag_contract_data = (HERE / "flags-contract.json").read_bytes()
    flag_contract = json.loads(flag_contract_data)
    if flag_contract.get("sql_sha256") != hashlib.sha256((HERE / "module-template/mosey-flags.sql").read_bytes()).hexdigest():
        raise ValueError("Mosey flag SQL differs from its inspected contract")
    expected_sql = flag_contract.get("sql_file_sha256")
    if not isinstance(expected_sql, dict) or not expected_sql or any(
            hashlib.sha256((HERE / "module-template" / name).read_bytes()).hexdigest() != digest
            for name, digest in expected_sql.items()):
        raise ValueError("Boolean transactions or country release SQL differ from the validated contract")
    if (set(flag_contract.get("flags", {})) != {"45768305"} or
            flag_contract.get("legacy_country_migration", {}).get("managed") is not False):
        raise ValueError("Only the Mosey hopping Boolean may remain managed")
    files = {}
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        entries = [(str(p.relative_to(HERE / "module-template")), p.read_bytes(), p.suffix == ".sh")
                   for p in sorted((HERE / "module-template").rglob("*")) if p.is_file()]
        entries.append(("bin/onyx-mosey-nlmsg", data, True))
        entries.append(("flags-contract.json", flag_contract_data, False))
        if native_data is not None:
            entries.append(("system/system_ext/lib64/libmosey_onyx_config.so", native_data, False))
        if cache_data is not None:
            entries.append(("bin/onyx-mosey-cache", cache_data, True))
        for name, data, executable in sorted(entries):
            info = zipfile.ZipInfo(name, (2026, 11, 17, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if executable else 0o100644) << 16
            z.writestr(info, data, compresslevel=9)
            files[name] = hashlib.sha256(data).hexdigest()
    receipt = {"zip_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
               "files": files, "gms_version_code": 264630035,
               "phenotype_schema_version": 1036,
               "namespace": "com.google.android.gms.nearby", "flag": "45704091",
               "mosey_namespace": "mosey_app_android#com.google.android.mosey",
               "mosey_flags": {"45768305": True},
               "managed_flags": flag_contract["managed_flags"],
               "country_pin_managed": False,
               "legacy_country_release": flag_contract["legacy_country_migration"],
               "mosey_version_code": 60715,
               "mosey_flag_contract": flag_contract,
               "static_selinux_policy_included": False, "replaces_system_files": native_data is not None,
               "policy_helper_sha256": digest, "policy_helper_clearance": proof}
    if native_proof is not None:
        receipt["native_adapter_clearance"] = native_proof
    if cache_proof is not None:
        receipt["shared_cache_clearance"] = cache_proof
    output.with_suffix(".json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--policy-helper", type=Path, required=True)
    parser.add_argument("--policy-clearance", type=Path, required=True)
    parser.add_argument("--native-library", type=Path)
    parser.add_argument("--native-clearance", type=Path)
    parser.add_argument("--cache-helper", type=Path)
    parser.add_argument("--cache-clearance", type=Path)
    args = parser.parse_args()
    receipt = build(args.output.resolve(), args.policy_helper.resolve(), args.policy_clearance.resolve(),
                    args.native_library.resolve() if args.native_library else None,
                    args.native_clearance.resolve() if args.native_clearance else None,
                    args.cache_helper.resolve() if args.cache_helper else None,
                    args.cache_clearance.resolve() if args.cache_clearance else None)
    print(args.output)
    print(receipt["zip_sha256"])
