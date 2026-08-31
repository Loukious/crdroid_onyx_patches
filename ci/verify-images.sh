#!/usr/bin/env bash
#
# Post-build gate: prove the packed boot-chain images actually contain the
# vendor kernel modules, and fail the job if they do not.
#
# Why this exists: crave build 296544 shipped an OTA whose vendor_boot ramdisk
# had ZERO .ko files (33 cpio entries vs 422 on the known-good build) and whose
# vendor_dlkm.img was ~340 KB (known-good: 32 MB). The phone bootlooped before
# SystemServer and Virtual A/B rolled the slot back. The build had compiled all
# 574 modules and staged 385 of them into vendor_ramdisk/ -- ninja simply packed
# the images from a pre-module state, because on a resumed out/ the kernel Image
# edge can look clean (same mtime) while installclean has wiped the module
# staging dirs, letting the vendor_boot/vendor_dlkm packing edges run before
# the kernel recipe reinstalls the modules. mka exits 0 either way, so only an
# output check can catch it.
#
# Usage: verify-images.sh [TREE_ROOT]     (DEVICE from env, default onyx)
# Exit 0 = images good; exit 1 = do not publish this build.
set -uo pipefail

TREE="${1:-.}"
DEVICE="${DEVICE:-onyx}"
PRODUCT_OUT="$TREE/out/target/product/$DEVICE"
HOST="$TREE/out/host/linux-x86/bin"

# Known-good reference build (2026-08-28, local): 385 .ko in the vendor_boot
# ramdisk, vendor_dlkm.img 32.8 MB, system_dlkm.img 7.5 MB. Thresholds are
# deliberately generous -- they only need to separate "modules packed" from
# "modules missing", which is 385 vs 0 and 32 MB vs 0.3 MB.
MIN_BOOT_MODULES=200
MIN_VDLKM_BYTES=$((16 * 1024 * 1024))
MIN_SDLKM_BYTES=$((3 * 1024 * 1024))

fail() { echo "VERIFY-FAIL: $*"; FAILED=1; }
FAILED=0

for f in vendor_boot.img vendor_dlkm.img system_dlkm.img; do
    [ -f "$PRODUCT_OUT/$f" ] || fail "$PRODUCT_OUT/$f does not exist"
done
[ "$FAILED" = 1 ] && { echo "verify-images: missing images, not continuing"; exit 1; }

# ---------------------------------------------------------------- vendor_boot
# Unpack the vendor ramdisk and count .ko entries in the cpio. unpack_bootimg
# writes the ramdisk fragments as stored (lz4-compressed); lz4 -d passes a
# plain file through with an error, so try decompress and fall back to cp.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
"$HOST/unpack_bootimg" --boot_img "$PRODUCT_OUT/vendor_boot.img" --out "$TMP" \
    >"$TMP/unpack.log" 2>&1 \
    || { fail "unpack_bootimg could not read vendor_boot.img (see $TMP/unpack.log)"; exit 1; }

# The general vendor ramdisk fragment is vendor_ramdisk00 (a by-name entry
# points at it); with BOARD_VENDOR_RAMDISK_FRAGMENTS unset there is exactly one.
RAMDISK="$(ls "$TMP"/vendor_ramdisk* 2>/dev/null | head -1)"
[ -n "$RAMDISK" ] || { fail "no vendor_ramdisk* fragment in unpacked vendor_boot.img"; exit 1; }

if "$HOST/lz4" -d "$RAMDISK" "$RAMDISK.cpio" >/dev/null 2>&1; then
    CPIOS="$RAMDISK.cpio"
else
    CPIOS="$RAMDISK"
fi

COUNT="$(python3 - "$CPIOS" <<'PYEOF'
import sys
# Count *.ko entries in a (possibly concatenated) newc cpio.
data = open(sys.argv[1], 'rb').read()
off, names = 0, 0
while off + 110 <= len(data):
    if data[off:off+6] not in (b'070701', b'070702'):
        break
    fs = int(data[off+54:off+62], 16)   # filesize
    ns = int(data[off+94:off+102], 16)  # namesize
    name = data[off+110:off+110+ns-1]
    if name.endswith(b'.ko'):
        names += 1
    off += 110 + ns
    off = (off + 3) & ~3
    off += fs
    off = (off + 3) & ~3
print(names)
PYEOF
)" || COUNT=""

if [ -z "$COUNT" ]; then
    fail "could not parse the vendor ramdisk cpio to count modules"
else
    echo "vendor_boot ramdisk: $COUNT .ko files"
    [ "$COUNT" -ge "$MIN_BOOT_MODULES" ] \
        || fail "vendor_boot ramdisk has only $COUNT .ko (expected >= $MIN_BOOT_MODULES) -- the module packing step did not land in the image; see ci/crave-build.sh's postmortem note for the known ninja staleness cause"
fi

# --------------------------------------------------------------- dlkm images
vd=$(stat -c %s "$PRODUCT_OUT/vendor_dlkm.img")
sd=$(stat -c %s "$PRODUCT_OUT/system_dlkm.img")
echo "vendor_dlkm.img: $vd bytes; system_dlkm.img: $sd bytes"
[ "$vd" -ge "$MIN_VDLKM_BYTES" ] || fail "vendor_dlkm.img is only $vd bytes (expected >= $MIN_VDLKM_BYTES) -- vendor_dlkm modules are missing"
[ "$sd" -ge "$MIN_SDLKM_BYTES" ] || fail "system_dlkm.img is only $sd bytes (expected >= $MIN_SDLKM_BYTES) -- system_dlkm modules are missing"

# ------------------------------------------------------------------ staleness
# Nothing staged into the module dirs may be newer than the image that is
# supposed to contain it. A newer staged module means the kernel recipe ran
# after packing (the 296544 failure mode: modules were installed into
# vendor_ramdisk/ three minutes after vendor_boot.img had already been packed
# from the empty dir).
for pair in "vendor_boot.img vendor_ramdisk" "vendor_dlkm.img vendor_dlkm"; do
    set -- $pair
    img="$PRODUCT_OUT/$1"; dir="$PRODUCT_OUT/$2/lib/modules"
    if [ -d "$dir" ]; then
        # -print -quit, not a `| grep -q .` pipe: under pipefail, grep -q
        # exiting on the match SIGPIPEs find (141) and the test reads false.
        newer="$(find "$dir" -name '*.ko' -newer "$img" -print -quit)"
        if [ -n "$newer" ]; then
            fail "$1 is older than the modules staged in $2/lib/modules -- the image was packed before module install"
        fi
    fi
done

if [ "$FAILED" = 1 ]; then
    echo
    echo "verify-images: REFUSING this build. Do not publish or flash it."
    exit 1
fi
echo "verify-images: vendor_boot and dlkm images contain the kernel modules."
exit 0
