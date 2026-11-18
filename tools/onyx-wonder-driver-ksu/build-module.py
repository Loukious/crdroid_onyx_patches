#!/usr/bin/env python3
"""Package a separately compiled, explicitly reviewed QCA module; never build it."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zipfile

HERE = Path(__file__).resolve().parent
NAME = "qca_cld3_wcn7750"
RELEASE = "6.18.63-android17-6-maybe-dirty-4k"
VERMAGIC = RELEASE + " SMP preempt mod_unload modversions aarch64"
STOCK_SHA = "0a2eba04b57ccdc0ae9e57258b91b38440e4b983fa9e151fe5acf36a3d915969"
REFERENCE_SHA = {
    "gki/Image": "9a976923a0897e8930900154bcf64ead7a2266c7e92c2e14b3623add6aaab878",
    "gki/kernel_aarch64_dot_config": "3fc1fb8c15e9a0e1519d0898a46022907061374a442787db8073a48db3821186",
    "gki/kernel_aarch64_Module.symvers": "0dac96a122974062c793ef5166f44754f15f81feb3dbf3293c8a7e1168d85d37",
    "platform/qca_cld3_wcn7750_Module.symvers": "3eb0a7812b8a1c46909e391529235d2b6d2a2d0675b4585ba57b1551b64eb0e8",
}
REQUIRED_REVIEWS = (
    "source_lifecycle_fix_reviewed", "ordinary_module_unload_path_reviewed",
    "synchronous_post_fs_data_reload_reviewed", "kernel_and_dependencies_unchanged",
)
REQUIRED_SOURCES = {
    "modules/qcacld-3.0/core/hdd/src/wlan_hdd_main.c",
    "modules/qcacld-3.0/core/hdd/src/wlan_hdd_wonder.c",
}
SCAFFOLD_PATHS = ("module-template/common.sh", "module-template/customize.sh",
                  "module-template/post-fs-data.sh", "module-template/module.prop", "build-module.py")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sections(data):
    if (len(data) < 64 or data[:6] != b"\x7fELF\x02\x01" or
            struct.unpack_from("<HH", data, 16) != (1, 183)):
        raise ValueError("QCA module must be an ELF64 little-endian ARM64 relocatable object")
    offset = struct.unpack_from("<Q", data, 40)[0]
    size, count, strings_index = struct.unpack_from("<HHH", data, 58)
    if size != 64 or not count or strings_index >= count or offset + size * count > len(data):
        raise ValueError("Unsupported ELF section table")
    headers = [struct.unpack_from("<IIQQQQIIQQ", data, offset + i * size) for i in range(count)]
    def contents(header):
        start, length = header[4:6]
        if start + length > len(data):
            raise ValueError("ELF section extends beyond the module")
        return data[start:start + length]
    names = contents(headers[strings_index])
    result = {}
    for header in headers:
        end = names.find(b"\0", header[0])
        if header[0] >= len(names) or end < 0:
            raise ValueError("Invalid ELF section name")
        name = names[header[0]:end].decode("ascii")
        if name in result:
            raise ValueError("Duplicate ELF section")
        if header[1] != 8:
            result[name] = contents(header)
    return result


def modinfo(elf):
    result = {}
    for entry in elf.get(".modinfo", b"").split(b"\0"):
        if not entry:
            continue
        key, value = entry.decode("utf-8").split("=", 1)
        result.setdefault(key, []).append(value)
    return result


def imports(elf):
    result = {}
    def add(name, crc):
        if not name or (name in result and result[name] != crc):
            raise ValueError("Empty or conflicting versioned imported symbol")
        result[name] = crc
    classic = elf.get("__versions", b"")
    if len(classic) % 64:
        raise ValueError("Invalid classic modversions section")
    for offset in range(0, len(classic), 64):
        name = classic[offset + 8:offset + 64]
        if b"\0" not in name:
            raise ValueError("Unterminated imported symbol")
        add(name.split(b"\0", 1)[0].decode(), struct.unpack_from("<Q", classic, offset)[0])
    names, crcs = elf.get("__version_ext_names"), elf.get("__version_ext_crcs")
    if names is not None or crcs is not None:
        if names is None or crcs is None or len(crcs) % 4 or not names.endswith(b"\0"):
            raise ValueError("Invalid extended modversions sections")
        names = names.rstrip(b"\0").split(b"\0")
        if len(names) != len(crcs) // 4:
            raise ValueError("Extended imported CRC count differs")
        for name, (crc,) in zip(names, struct.iter_unpack("<I", crcs)):
            add(name.decode(), crc)
    if not result:
        raise ValueError("Module has no versioned imported symbols")
    return result


def exported_map(path):
    result = {}
    for line in path.read_text().splitlines():
        fields = line.split()
        if len(fields) < 4 or fields[2] != NAME or fields[1] in result:
            raise ValueError("QCA Module.symvers must contain unique QCA exports only")
        result[fields[1]] = (int(fields[0], 16), *fields[3:])
    if not result:
        raise ValueError("QCA export table is empty")
    return result


def validate(module, stock, replacement_symvers, reference_artifact, source_root, clearance):
    data, stock_data = module.read_bytes(), stock.read_bytes()
    proof = json.loads(clearance.read_text())
    if (proof.get("schema") != 1 or proof.get("reviewed") is not True or
            not isinstance(proof.get("reviewed_by"), str) or not proof["reviewed_by"].strip() or
            proof.get("scope") != "qca-module-only" or
            any(proof.get(key) is not True for key in REQUIRED_REVIEWS)):
        raise ValueError("A reviewer-authored successful clearance is required")
    if (digest(stock_data) != STOCK_SHA or proof.get("stock_sha256") != STOCK_SHA or
            proof.get("replacement_sha256") != digest(data) or digest(data) == STOCK_SHA or
            proof.get("kernel_release") != RELEASE or
            proof.get("replacement_symvers_sha256") != digest(replacement_symvers.read_bytes())):
        raise ValueError("Module identity differs from the reviewed clearance")
    for relative, expected in REFERENCE_SHA.items():
        if digest((reference_artifact / relative).read_bytes()) != expected:
            raise ValueError("Retained reference kernel artifact differs: " + relative)
    config = (reference_artifact / "gki/kernel_aarch64_dot_config").read_text()
    if "\nCONFIG_MODULE_UNLOAD=y\n" not in config or "\nCONFIG_MODULE_FORCE_UNLOAD=y\n" in config:
        raise ValueError("Reference kernel lacks the reviewed ordinary-unload configuration")
    reviewed = proof.get("reviewed_source_sha256")
    if not isinstance(reviewed, dict) or not REQUIRED_SOURCES <= set(reviewed):
        raise ValueError("Both QCA lifecycle source files must be covered by the source review")
    for relative, expected in reviewed.items():
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("Review source paths must be relative and safe")
        resolved = (source_root / path).resolve()
        if not resolved.is_relative_to(source_root.resolve()) or digest(resolved.read_bytes()) != expected:
            raise ValueError("Reviewed source changed: " + relative)
    expected_scaffold = {name: digest((HERE / name).read_bytes()) for name in SCAFFOLD_PATHS}
    if proof.get("reviewed_scaffold_sha256") != expected_scaffold:
        raise ValueError("Driver scaffold differs from the reviewed clearance")
    replacement, original = sections(data), sections(stock_data)
    replacement_info, original_info = modinfo(replacement), modinfo(original)
    for key, expected in (("name", [NAME]), ("vermagic", [VERMAGIC])):
        if replacement_info.get(key) != expected or original_info.get(key) != expected:
            raise ValueError("Unexpected QCA " + key)
    if replacement_info.get("depends") != original_info.get("depends"):
        raise ValueError("QCA dependency list changed")
    if replacement_info.get("parmtype") != original_info.get("parmtype"):
        raise ValueError("QCA module parameter contract changed")
    original_imports = imports(original)
    if len(original_imports) != 566 or imports(replacement) != original_imports:
        raise ValueError("Imported symbol/CRC map differs from the accepted 566-import stock module")
    baseline_symvers = reference_artifact / "platform/qca_cld3_wcn7750_Module.symvers"
    baseline_exports = exported_map(baseline_symvers)
    if exported_map(replacement_symvers) != baseline_exports:
        raise ValueError("Exported QCA names/CRCs/flags/namespaces changed")
    for section in ("__kcrctab", "__ksymtab_strings", "__kflagstab"):
        if not original.get(section) or replacement.get(section) != original[section]:
            raise ValueError("Actual QCA exported ABI section changed: " + section)
    if not replacement.get(".exit.text") or not original.get(".exit.text"):
        raise ValueError("QCA exit function is missing")
    if not any(value.startswith("wonder_lifecycle_revision:") for value in replacement_info.get("parm", [])):
        raise ValueError("Reviewed getter-only lifecycle revision marker is missing")
    note = original.get(".note.gnu.build-id")
    replacement_note = replacement.get(".note.gnu.build-id")
    if not note or not replacement_note or note == replacement_note:
        raise ValueError("Distinct stock and replacement QCA build notes are required")
    return data, proof, digest(note), digest(replacement_note), len(baseline_exports)


def build(output, module, stock, replacement_symvers, reference_artifact, source_root, clearance):
    data, proof, stock_note_sha, replacement_note_sha, export_count = validate(
        module, stock, replacement_symvers, reference_artifact, source_root, clearance)
    receipt_path = output.with_suffix(".json")
    if output.exists() or receipt_path.exists():
        raise ValueError("Output ZIP or receipt already exists")
    entries = [(p.name, p.read_bytes(), p.suffix == ".sh")
               for p in sorted((HERE / "module-template").iterdir()) if p.is_file()]
    # Presence of skip_mount explicitly opts out of system/vendor overlay mounting.
    entries += [
        ("skip_mount", b"", False),
        ("payload/" + NAME + ".ko", data, False),
        ("payload-contract.sh", (
            "# Generated by the reviewed-artifact packager.\n"
            "WDR_REPLACEMENT_SHA=" + digest(data) + "\n"
            "WDR_STOCK_NOTE_SHA=" + stock_note_sha + "\n"
            "WDR_REPLACEMENT_NOTE_SHA=" + replacement_note_sha + "\n").encode(), False),
        ("review-clearance.json", (json.dumps(proof, indent=2) + "\n").encode(), False),
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    files = {}
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, contents, executable in sorted(entries):
            info = zipfile.ZipInfo(name, (2026, 11, 17, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if executable else 0o100644) << 16
            archive.writestr(info, contents)
            files[name] = digest(contents)
    report = {
        "zip_sha256": digest(output.read_bytes()), "replacement_sha256": digest(data),
        "stock_sha256": STOCK_SHA, "stock_note_sha256": stock_note_sha,
        "replacement_note_sha256": replacement_note_sha,
        "kernel_release": RELEASE, "reference_sha256": REFERENCE_SHA,
        "imported_symbols_checked": 566, "exported_symbols_checked": export_count,
        "files": files, "review_clearance": proof,
        "kernel_build_performed": False, "device_changes": False,
        "overlay_mounting": False, "reload_stage": "synchronous-post-fs-data",
    }
    with receipt_path.open("x") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "module", "stock-module", "replacement-symvers", "reference-artifact", "source-root", "clearance"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    report = build(args.output.resolve(), args.module.resolve(), args.stock_module.resolve(),
                   args.replacement_symvers.resolve(), args.reference_artifact.resolve(),
                   args.source_root.resolve(), args.clearance.resolve())
    print(args.output)
    print(report["zip_sha256"])
