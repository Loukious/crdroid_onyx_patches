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
# konoha-abi-prep.sh reads SYMVERS_URL / SYMVERS_SHA256_URL from the
# environment. Its default, used when this helper exports nothing, is the
# legacy wlan-kernel-symbols release. Releases published before 2026-09-14
# have no Module.symvers asset; those warn loudly and fall back.
#
# Exports: SYMVERS_URL, SYMVERS_SHA256_URL (only on success).

_pin_tag_file="vendor/extra/kernel/onyx/.kernel-release-tag"

if [ ! -s "$_pin_tag_file" ]; then
    echo "pin-konoha-symvers: no .kernel-release-tag staged (SKIP_KERNEL=1 or an" \
         "old apply.sh); the wlan build uses konoha-abi-prep.sh defaults"
    unset _pin_tag_file
    return 0
fi

_pin_tag="$(cat "$_pin_tag_file")"
_pin_url="https://github.com/Loukious/konoha-kernel-gki/releases/download/${_pin_tag}/Module.symvers"

# Probe before exporting: an old release without the asset must fall back
# rather than die mid-prep with a 404 on the symvers download. Silent on
# purpose -- the 404 is expected here and the WARNING below says it better.
if curl -fsI -o /dev/null --retry 2 "$_pin_url"; then
    export SYMVERS_URL="$_pin_url"
    export SYMVERS_SHA256_URL="${_pin_url}.sha256"
    echo "pin-konoha-symvers: Module.symvers pinned to kernel release $_pin_tag"
else
    echo "WARNING: pin-konoha-symvers: kernel release $_pin_tag has no Module.symvers asset" >&2
    echo "WARNING: falling back to the legacy wlan-kernel-symbols release (may be stale)" >&2
fi

unset _pin_tag_file _pin_tag _pin_url
