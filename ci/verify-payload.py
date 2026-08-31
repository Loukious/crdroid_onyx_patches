#!/usr/bin/env python3
"""Verify what an OTA zip actually ships, by reading its payload.bin.

The OTA payload's partition images are NOT the loose out/.../*.img files:
add_img_to_target_files rebuilds vendor_boot from its own staging tree at
whatever moment ninja schedules the target-files edge. In crave job 296582
(run 17, 2026-08-31) that edge ran before the kernel modules were distributed
into vendor_ramdisk/, so the payload shipped a vendor_boot with 0 .ko files
while the loose image -- which the verify gate checked -- was good. The only
artifact that cannot lie is the shipped zip itself.

This script parses the payload manifest straight from the protobuf wire
format (no google.protobuf import: ota_from_target_files.py does not use it,
so nothing proves the build server's python3 has it installed) and
reconstructs the vendor_boot partition image from its install operations.
The reconstruction is self-checking: the sha256 of the rebuilt image must
equal the hash delta_generator recorded in the manifest, so a parsing bug
cannot silently produce a wrong-but-passing image.

Usage: verify-payload.py <OTA_ZIP> <OUTDIR>
Writes <OUTDIR>/payload_vendor_boot.img and <OUTDIR>/payload_info
(key=value lines: VENDOR_DLKM_SIZE). Exit 0 = payload parsed and hash-checked.
"""
import bz2
import hashlib
import lzma
import struct
import sys
import zipfile

OTA_ZIP = sys.argv[1]
OUTDIR = sys.argv[2]

# InstallOperation.Type values, from system/update_engine/update_metadata.proto
OP_REPLACE = 0
OP_REPLACE_BZ = 1
OP_REPLACE_XZ = 8
OP_ZERO = 6
OP_DISCARD = 7

BLOCK_SIZE = 4096  # manifest default; every payload we generate uses this


def read_varint(buf, pos):
    result = 0
    shift = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7


def fields(buf):
    """Yield (field_number, wire_type, value) for a protobuf message body."""
    pos = 0
    while pos < len(buf):
        key, pos = read_varint(buf, pos)
        fn, wt = key >> 3, key & 7
        if wt == 0:
            v, pos = read_varint(buf, pos)
            yield fn, v
        elif wt == 2:
            ln, pos = read_varint(buf, pos)
            yield fn, buf[pos:pos + ln]
            pos += ln
        elif wt == 1:
            yield fn, buf[pos:pos + 8]
            pos += 8
        elif wt == 5:
            yield fn, buf[pos:pos + 4]
            pos += 4
        else:
            raise ValueError(f"unsupported wire type {wt} (field {fn})")


def one(buf, want, default=None):
    """First value of field `want` in a message body, or default."""
    for fn, v in fields(buf):
        if fn == want:
            return v
    return default


def many(buf, want):
    return [v for fn, v in fields(buf) if fn == want]


def parse_partition(body):
    p = {"name": None, "size": 0, "hash": b"", "ops": []}
    for fn, v in fields(body):
        if fn == 1:                      # partition_name
            p["name"] = v.decode()
        elif fn == 7:                    # new_partition_info
            p["size"] = one(v, 1, 0)
            p["hash"] = one(v, 2, b"") or b""
        elif fn == 8:                    # operations (repeated)
            op = {"type": 0, "off": 0, "len": 0, "extents": []}
            for ofn, ov in fields(v):
                if ofn == 1:             # type
                    op["type"] = ov
                elif ofn == 2:           # data_offset
                    op["off"] = ov
                elif ofn == 3:           # data_length
                    op["len"] = ov
                elif ofn == 6:           # dst_extents (repeated)
                    op["extents"].append((one(ov, 1, 0), one(ov, 2, 0)))
            p["ops"].append(op)
    return p


def die(msg):
    print(f"verify-payload: FATAL: {msg}", file=sys.stderr)
    sys.exit(1)


with zipfile.ZipFile(OTA_ZIP) as z:
    if "payload.bin" not in z.namelist():
        die(f"{OTA_ZIP} has no payload.bin (not an A/B OTA zip?)")
    with z.open("payload.bin") as f:
        magic = f.read(4)
        if magic != b"CrAU":
            die(f"bad payload magic {magic!r}")
        version, manifest_size = struct.unpack(">QQ", f.read(16))
        if version < 2:
            die(f"payload version {version} has no metadata signature field")
        sig_size = struct.unpack(">I", f.read(4))[0]
        manifest_body = f.read(manifest_size)
        data_start = 24 + manifest_size + sig_size
        print(f"payload: version={version} manifest={manifest_size}B "
              f"blobs@{data_start}")

        partitions = [parse_partition(p) for p in many(manifest_body, 13)]
        if not partitions:
            die("payload manifest lists no partitions")

        vdlkm = next((p for p in partitions if p["name"] == "vendor_dlkm"), None)
        if vdlkm is None:
            die("payload has no vendor_dlkm partition")
        print(f"payload vendor_dlkm: {vdlkm['size']} bytes")

        vb = next((p for p in partitions if p["name"] == "vendor_boot"), None)
        if vb is None:
            die("payload has no vendor_boot partition")
        if not vb["hash"]:
            die("payload manifest has no vendor_boot hash -- cannot self-check")
        print(f"payload vendor_boot: {len(vb['ops'])} ops, {vb['size']} bytes")

        out_path = f"{OUTDIR}/payload_vendor_boot.img"
        with open(out_path, "wb") as out:
            out.truncate(vb["size"])   # ZERO/DISCARD extents read back as 0
            digest = hashlib.sha256()
            # The image is sparse in the sense that ops target scattered
            # dst_extents; hash it sequentially afterwards instead of while
            # writing out of order.
            for i, op in enumerate(vb["ops"]):
                total = sum(nb for _, nb in op["extents"]) * BLOCK_SIZE
                if op["type"] in (OP_ZERO, OP_DISCARD):
                    blob = b"\x00" * total
                elif op["type"] == OP_REPLACE:
                    f.seek(data_start + op["off"])
                    blob = f.read(op["len"])
                elif op["type"] == OP_REPLACE_BZ:
                    f.seek(data_start + op["off"])
                    blob = bz2.decompress(f.read(op["len"]))
                elif op["type"] == OP_REPLACE_XZ:
                    f.seek(data_start + op["off"])
                    blob = lzma.decompress(f.read(op["len"]))
                else:
                    die(f"op {i}: type {op['type']} is a diff op -- not "
                        f"expected in a full OTA")
                if len(blob) != total:
                    die(f"op {i}: decompressed {len(blob)}B but extents "
                        f"cover {total}B")
                pos = 0
                for start_block, num_blocks in op["extents"]:
                    out.seek(start_block * BLOCK_SIZE)
                    out.write(blob[pos:pos + num_blocks * BLOCK_SIZE])
                    pos += num_blocks * BLOCK_SIZE

        digest = hashlib.sha256()
        with open(out_path, "rb") as out:
            while True:
                chunk = out.read(8 << 20)
                if not chunk:
                    break
                digest.update(chunk)

        got = digest.hexdigest()
        want = vb["hash"].hex()
        if got != want:
            die(f"vendor_boot reconstruction hash mismatch: got {got} "
                f"want {want} -- extraction is broken, do NOT trust it")
        print(f"payload vendor_boot: sha256 {got} (matches manifest)")

with open(f"{OUTDIR}/payload_info", "w") as info:
    info.write(f"VENDOR_DLKM_SIZE={vdlkm['size']}\n")
    info.write(f"VENDOR_BOOT_IMG={out_path}\n")
print(f"verify-payload: OK -- {out_path}")
