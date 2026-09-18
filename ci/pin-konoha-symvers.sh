#!/usr/bin/env bash
# Pin the qcacld-3.0 Module.symvers to the kernel release this build ships.
#
# Source (not execute) from a build recipe, after apply.sh has run and with
# the ROM source root as the working directory:
#
#     source "$PATCHES/ci/pin-konoha-symvers.sh"
#
# apply.sh's stage_kernel records the kernel release tag it staged in
# vendor/extra/kernel/onyx/.kernel-release-tag. The kernel's own releases
# (nethunter-*, custom-build-*) carry that kernel's Module.symvers +
# Module.symvers.sha256 as release assets, so the wlan module gets built
# against exactly the kernel the ROM ships. This removes the manually
# maintained wlan-kernel-symbols refresh step that broke crave build 299960
# (stale .sha256) and would drift silently the other way.
#
# Persist the URL outside git projects: Android filters exported variables
# before ninja, so the compile-time validation must read the same file.
# Missing release assets are fatal, never a reason to use legacy symbols.
#
# Exports: SYMVERS_URL, SYMVERS_SHA256_URL (only on success).

_pin_tag_file="vendor/extra/kernel/onyx/.kernel-release-tag"

if [ ! -s "$_pin_tag_file" ]; then
    echo "FATAL: pin-konoha-symvers: no staged kernel release tag" >&2
    unset _pin_tag_file
    return 1
fi

_pin_tag="$(cat "$_pin_tag_file")"
_pin_url="https://github.com/Loukious/konoha-kernel-gki/releases/download/${_pin_tag}/Module.symvers"

# Probe before exporting: an old release without the asset must fall back
# rather than die mid-prep with a 404 on the symvers download. Silent on
# purpose -- the 404 is expected here and the WARNING below says it better.
if curl -fsI -o /dev/null --retry 2 "$_pin_url"; then
    export SYMVERS_URL="$_pin_url"
    export SYMVERS_SHA256_URL="${_pin_url}.sha256"
    mkdir -p kernel/xiaomi/konoha-abi
    printf '%s\n' "$_pin_url" > kernel/xiaomi/konoha-abi/.symvers-pin.tmp
    mv kernel/xiaomi/konoha-abi/.symvers-pin.tmp kernel/xiaomi/konoha-abi/.symvers-pin
    echo "pin-konoha-symvers: Module.symvers pinned to kernel release $_pin_tag"
else
    echo "FATAL: pin-konoha-symvers: cannot access Module.symvers for $_pin_tag" >&2
    return 1
fi

unset _pin_tag_file _pin_tag _pin_url
