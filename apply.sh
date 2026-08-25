#!/usr/bin/env bash
#
# Apply the crDroid onyx patch set to a synced tree, overlay the OS3.0.302.0
# firmware blobs, and stage the Kono-Ha kernel Image that
# vendor/extra/BoardConfigKernel.mk expects.
#
# Safe to run repeatedly: each patch is reverse-checked first, so an already
# patched tree is left alone instead of failing. Any patch that neither applies
# nor is already applied is a hard error -- better to stop than to ship a
# half-patched ROM.
#
# usage: apply.sh [<rom root>]
#   env: KERNEL_RELEASE_TAG   konoha release to pull the Image from (default: latest)
#        SKIP_KERNEL=1        don't fetch/stage the kernel Image
#        SKIP_FIRMWARE=1      don't overlay the firmware blobs
#        GITHUB_TOKEN         used for the release API if the repo is private
#
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROM="$(cd "${1:-$PWD}" && pwd)"

KERNEL_REPO="${KERNEL_REPO:-Loukious/konoha-kernel-gki}"
KERNEL_DEST="vendor/extra/kernel/onyx/Image"

red()  { printf '\033[31m%s\033[0m\n' "$*"; }
grn()  { printf '\033[32m%s\033[0m\n' "$*"; }
ylw()  { printf '\033[33m%s\033[0m\n' "$*"; }

[ -d "$ROM/.repo" ] || { red "FATAL: $ROM is not a repo tree (no .repo)"; exit 1; }

# patch directory name -> project path. Explicit rather than s|_|/| so that a
# project whose path component contains an underscore can't silently break.
declare -A PROJECT=(
    [build_release]="build/release"
    [device_xiaomi_onyx]="device/xiaomi/onyx"
    [frameworks_base]="frameworks/base"
    [packages_modules_Bluetooth]="packages/modules/Bluetooth"
    [packages_modules_common]="packages/modules/common"
    [vendor_lineage]="vendor/lineage"
    [vendor_pixel_launcher]="vendor/pixel/launcher"
    [vendor_qcom_opensource_interfaces]="vendor/qcom/opensource/interfaces"
    [vendor_xiaomi_onyx]="vendor/xiaomi/onyx"
)

fail=0 applied=0 already=0

for pdir in "$HERE"/patches/*/; do
    [ -d "$pdir" ] || continue   # unexpanded glob: no patch dirs at all
    key="$(basename "$pdir")"
    proj="${PROJECT[$key]:-}"
    if [ -z "$proj" ]; then
        red "FATAL: no project mapping for patches/$key"; fail=1; continue
    fi
    if [ ! -d "$ROM/$proj" ]; then
        red "FATAL: $proj missing from the tree (sync incomplete?)"; fail=1; continue
    fi

    echo "== $proj"
    for patch in "$pdir"*.patch; do
        [ -e "$patch" ] || continue
        n="$(basename "$patch")"

        # Already applied? Then the reverse patch applies cleanly.
        if git -C "$ROM/$proj" apply --reverse --check "$patch" 2>/dev/null; then
            echo "   -- $n (already applied)"
            already=$((already+1))
            continue
        fi

        if git -C "$ROM/$proj" apply --3way --whitespace=nowarn "$patch" 2>/dev/null; then
            grn "   ++ $n"
            applied=$((applied+1))
        elif git -C "$ROM/$proj" apply --whitespace=nowarn "$patch" 2>/dev/null; then
            # --3way needs the pre-image blobs in the object store; on a
            # shallow sync they may be absent, so retry with plain context.
            grn "   ++ $n (context match)"
            applied=$((applied+1))
        else
            red "   !! $n FAILED"
            git -C "$ROM/$proj" apply --3way --whitespace=nowarn "$patch" 2>&1 \
                | sed 's/^/         /' | head -10
            fail=1
        fi
    done
done

# ------------------------------------------------------------- firmware overlay
# vendor/xiaomi/onyx is synced from crDroid's upstream GitLab (4GB, hosted for
# free by them). Only the ~350MB that actually differs -- the OS3.0.302.0 radio
# images and the two LHDC byte-patched blobs -- lives in our own project, and
# gets copied over the top here. A `repo sync --force-sync` reverts these; that
# is fine, apply.sh runs after every sync.
overlay_firmware() {
    local src="$ROM/vendor/xiaomi/onyx-firmware"
    local dst="$ROM/vendor/xiaomi/onyx"
    [ -d "$src" ] || { red "FATAL: $src missing -- is onyx-firmware in the local manifest?"; return 1; }
    [ -d "$dst" ] || { red "FATAL: $dst missing (sync incomplete?)"; return 1; }

    # Reassemble the two images that were split to stay under GitHub's 100MB
    # non-LFS blob limit, and check them against the recorded digest.
    local first base want have
    while IFS= read -r first; do
        base="${first#./}"; base="${base%.part00}"
        [ -f "$src/$base.sha256" ] || { red "FATAL: no $base.sha256"; return 1; }
        want="$(cat "$src/$base.sha256")"
        if [ -f "$dst/$base" ] && [ "$(sha256sum "$dst/$base" | cut -d' ' -f1)" = "$want" ]; then
            echo "   -- $base (already current)"
            continue
        fi
        mkdir -p "$dst/$(dirname "$base")"
        cat "$src/$base".part?? > "$dst/$base" || { red "FATAL: cat failed for $base"; return 1; }
        have="$(sha256sum "$dst/$base" | cut -d' ' -f1)"
        if [ "$have" != "$want" ]; then
            red "FATAL: $base reassembled to $have, expected $want"
            return 1
        fi
        grn "   ++ $base (reassembled, $(stat -c%s "$dst/$base") bytes, sha256 ok)"
    done < <(cd "$src" && find . -name '*.part00' | sort)

    # Everything else is a straight copy.
    local n=0
    while IFS= read -r -d '' f; do
        f="${f#./}"
        cmp -s "$src/$f" "$dst/$f" && continue
        mkdir -p "$dst/$(dirname "$f")"
        cp -f "$src/$f" "$dst/$f" || { red "FATAL: cp failed for $f"; return 1; }
        echo "   ++ $f"
        n=$((n+1))
    done < <(cd "$src" && find . -type f \
                ! -path './.git/*' \
                ! -name '*.part[0-9][0-9]' ! -name '*.sha256' \
                ! -name 'README.md' ! -name '.gitattributes' -print0)
    echo "   ($n file(s) copied)"
}

if [ "${SKIP_FIRMWARE:-0}" != "1" ]; then
    echo "== firmware overlay"
    overlay_firmware || fail=1
fi

# ---------------------------------------------------------------- kernel Image
stage_kernel() {
    command -v unzip >/dev/null || { red "FATAL: unzip not found"; return 1; }

    local api="https://api.github.com/repos/$KERNEL_REPO/releases"
    local auth=()
    [ -n "${GITHUB_TOKEN:-}" ] && auth=(-H "Authorization: Bearer $GITHUB_TOKEN")

    local url
    if [ -n "${KERNEL_RELEASE_TAG:-}" ]; then
        url="$api/tags/$KERNEL_RELEASE_TAG"
    else
        url="$api/latest"
    fi

    local json
    json="$(curl -fsSL "${auth[@]}" -H 'Accept: application/vnd.github+json' "$url")" \
        || { red "FATAL: cannot read $url"; return 1; }

    # Want the KernelSU-Next root build WITHOUT charging bypass.
    local asset
    asset="$(printf '%s' "$json" \
        | grep -o '"browser_download_url": *"[^"]*\.zip"' \
        | sed 's/.*"\(https[^"]*\)"/\1/' \
        | grep -i 'KernelSU-Next' \
        | grep -iv 'bypasscharging' \
        | head -1)"

    if [ -z "$asset" ]; then
        red "FATAL: no non-bypasscharging KernelSU-Next zip in that release."
        ylw "       assets present:"
        printf '%s' "$json" | grep -o '"name": *"[^"]*\.zip"' | sed 's/^/         /'
        return 1
    fi

    ylw "   fetching $(basename "$asset")"
    local tmp; tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' RETURN
    curl -fsSL "${auth[@]}" -o "$tmp/ak3.zip" "$asset" || { red "FATAL: download failed"; return 1; }

    mkdir -p "$ROM/$(dirname "$KERNEL_DEST")"
    # AnyKernel3 ships the image compressed; fall back to the other names.
    if   unzip -l "$tmp/ak3.zip" | grep -q ' Image\.gz$'; then
        unzip -p "$tmp/ak3.zip" Image.gz | gunzip > "$ROM/$KERNEL_DEST"
    elif unzip -l "$tmp/ak3.zip" | grep -q ' Image\.lz4$'; then
        unzip -p "$tmp/ak3.zip" Image.lz4 | lz4 -d -c > "$ROM/$KERNEL_DEST"
    elif unzip -l "$tmp/ak3.zip" | grep -q ' Image$'; then
        unzip -p "$tmp/ak3.zip" Image > "$ROM/$KERNEL_DEST"
    else
        red "FATAL: no Image/Image.gz/Image.lz4 inside the zip:"
        unzip -l "$tmp/ak3.zip" | sed 's/^/         /'
        return 1
    fi

    # An arm64 kernel Image starts with the 'ARM\x64' magic at offset 0x38.
    local sz magic
    sz="$(stat -c%s "$ROM/$KERNEL_DEST")"
    magic="$(dd if="$ROM/$KERNEL_DEST" bs=1 skip=56 count=4 2>/dev/null | tr -d '\0')"
    if [ "$magic" != "ARM" ] && [ "$magic" != "ARMd" ]; then
        red "FATAL: $KERNEL_DEST is not an arm64 kernel Image (magic='$magic')"
        return 1
    fi
    grn "   ++ $KERNEL_DEST ($sz bytes)"
}

if [ "${SKIP_KERNEL:-0}" != "1" ]; then
    echo "== kernel"
    stage_kernel || fail=1
fi

echo
echo "applied=$applied already-applied=$already"
if [ "$fail" -ne 0 ]; then
    red "PATCHING FAILED - not safe to build"
    exit 1
fi
grn "patch set OK"
