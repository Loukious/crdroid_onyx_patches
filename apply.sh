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
#        apply.sh --preflight        validate everything that does NOT need a
#                                   synced tree, then exit. Runs in ~20s and is
#                                   meant to gate a build BEFORE it is submitted
#                                   to crave's queue, where a four-minute
#                                   failure costs three hours of waiting.
#   env: KERNEL_RELEASE_TAG   konoha release to pull the Image from (default: latest)
#        SKIP_KERNEL=1        don't fetch/stage the kernel Image
#        SKIP_FIRMWARE=1      don't overlay the firmware blobs
#        SKIP_OTA_METADATA=1  don't overlay vendor/crDroidOTA/<device>.json
#        GITHUB_TOKEN         used for the release API if the repo is private
#
# ---------------------------------------------------------------------------
# A NOTE ON PIPELINES, because it has already cost one build (crave 295566, a
# four-minute failure that took three hours of queue to reach).
#
# `pipefail` makes a pipeline's status the LAST NONZERO one, and that breaks two
# ways when a pipeline is used as a condition:
#
#   1. A nonzero PRODUCER that nonetheless printed exactly what you asked for.
#      `unzip -l` exits 1 on any warning -- junk prepended to the archive, for
#      instance -- while still printing a flawless listing. `unzip -l z | grep -q
#      ' Image\.gz$'` then reads as FALSE with Image.gz plainly in the listing.
#      This reproduces 3/3 and matches build 295566's log exactly, where the
#      diagnostic branch printed a listing that clearly contained Image.gz.
#
#   2. A consumer that EXITS EARLY. `grep -q`/`head -n` return at the first
#      match, the producer then takes SIGPIPE writing the rest, and pipefail
#      surfaces the 141. Verified here with `unzip -l | head -1` -> 141. It needs
#      the producer's output to exceed the 64 KB pipe buffer, so it is a latent
#      trap rather than what fired this time (an AnyKernel3 listing is ~1 KB).
#
# Rules for this file:
#   * Never put a pipeline in a condition. Capture the output into a variable
#     first, then match with a bash builtin. `preflight` greps for reintroductions.
#   * Better still, do not decide from a text listing at all -- attempt the
#     operation and validate the result. See extract_image.
# ---------------------------------------------------------------------------
#
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PREFLIGHT=0
if [ "${1:-}" = "--preflight" ]; then PREFLIGHT=1; shift; fi

ROM="$(cd "${1:-$PWD}" && pwd)"

DEVICE="${DEVICE:-onyx}"
KERNEL_REPO="${KERNEL_REPO:-Loukious/konoha-kernel-gki}"
KERNEL_DEST="vendor/extra/kernel/onyx/Image"

_TMPS=()
cleanup() { local d; for d in ${_TMPS[@]+"${_TMPS[@]}"}; do rm -rf "$d"; done; }
trap cleanup EXIT

red()  { printf '\033[31m%s\033[0m\n' "$*"; }
grn()  { printf '\033[32m%s\033[0m\n' "$*"; }
ylw()  { printf '\033[33m%s\033[0m\n' "$*"; }

# patch directory name -> project path. Explicit rather than s|_|/| so that a
# project whose path component contains an underscore can't silently break.
declare -A PROJECT=(
    [build_release]="build/release"
    [device_xiaomi_onyx]="device/xiaomi/onyx"
    [frameworks_base]="frameworks/base"
    [packages_apps_Settings]="packages/apps/Settings"
    [packages_apps_Updater]="packages/apps/Updater"
    [packages_modules_Bluetooth]="packages/modules/Bluetooth"
    [packages_modules_common]="packages/modules/common"
    [vendor_lineage]="vendor/lineage"
    [vendor_pixel_launcher]="vendor/pixel/launcher"
    [vendor_qcom_opensource_interfaces]="vendor/qcom/opensource/interfaces"
    [vendor_xiaomi_onyx]="vendor/xiaomi/onyx"
)

fail=0 applied=0 already=0

# ------------------------------------------------------------------- patching
apply_patches() {
    local pdir key proj patch n
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
                # Captured, not piped into head: see the pipeline note up top.
                local diag
                diag="$(git -C "$ROM/$proj" apply --3way --whitespace=nowarn "$patch" 2>&1)"
                printf '%s\n' "$diag" | sed -n '1,10p' | sed 's/^/         /'
                fail=1
            fi
        done
    done
}

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

# ---------------------------------------------------------- OTA metadata overlay
# vendor/lineage/build/tools/createjson.sh reads vendor/crDroidOTA/$DEVICE.json at
# `bacon` time to fill the maintainer / buildtype / donate fields of the OTA json
# it emits next to the zip. Upstream's copy names the official onyx maintainer and
# their PayPal, so it has to be replaced -- but *not* with a patch: upstream
# rewrites that file on every weekly release (filename, timestamp, md5, sha256,
# size all change), so a context patch there breaks about once a week and takes the
# whole build down with it. It did exactly that on 2026-08-26. A whole-file copy
# cannot conflict, and createjson.sh's extract_field() is grep/sed based, so it
# neither needs nor notices the rest of upstream's shape.
overlay_ota_metadata() {
    local src="$HERE/ota/crDroidOTA-$DEVICE.json"
    local dst="$ROM/vendor/crDroidOTA/$DEVICE.json"
    [ -f "$src" ] || { red "FATAL: $src missing"; return 1; }
    [ -d "$ROM/vendor/crDroidOTA" ] || { red "FATAL: vendor/crDroidOTA missing (sync incomplete?)"; return 1; }

    if cmp -s "$src" "$dst"; then
        echo "   -- $DEVICE.json (already current)"
        return 0
    fi
    cp -f "$src" "$dst" || { red "FATAL: cp failed for $DEVICE.json"; return 1; }
    grn "   ++ vendor/crDroidOTA/$DEVICE.json"
}

# ---------------------------------------------------------------- kernel Image
# zip_names <zipfile> -- newline-separated member names, empty on failure.
# `unzip -Z1` is one name per line and needs no parsing. The fallback exists
# because -Z is absent from a few stripped unzip builds; awk is used rather than
# grep|head because awk reads to EOF and so cannot lose a SIGPIPE race.
zip_names() {
    local out
    if out="$(unzip -Z1 "$1" 2>/dev/null)" && [ -n "$out" ]; then
        printf '%s' "$out"; return 0
    fi
    out="$(unzip -l "$1" 2>/dev/null \
           | awk 'NR>3 && NF>=4 { sub(/^ *[0-9]+ +[0-9-]+ +[0-9:]+ +/, ""); print }')"
    printf '%s' "$out"
}

# image_ok <file> -- true if <file> is a plausible raw arm64 kernel Image.
# An arm64 Image carries the magic 'ARM\x64' at offset 0x38.
image_ok() {
    local f="$1" sz mg
    sz="$(stat -c%s "$f" 2>/dev/null || echo 0)"
    [ "$sz" -ge 8000000 ] || return 1
    mg="$(dd if="$f" bs=1 skip=56 count=4 2>/dev/null | tr -d '\0')"
    [ "$mg" = "ARM" ] || [ "$mg" = "ARMd" ]
}

# extract_image <zip> <scratch> -- try each candidate member in turn and judge by
# the BYTES THAT COME OUT. Prints the member that worked.
#
# This deliberately does not parse `unzip -l`, which is what took build 295566
# down. Deciding from a listing makes the outcome depend on three things that
# have nothing to do with whether the member is present:
#   * the producer's exit status -- `unzip -l` exits 1 on any warning (e.g. junk
#     prepended to the archive) while still printing a flawless listing, and
#     pipefail turns that into a false condition. Reproduced 3/3, and it matches
#     the failed build's log exactly: the else branch printed a listing that
#     plainly contained Image.gz.
#   * the consumer not exiting early -- `grep -q` returning at the first match
#     SIGPIPEs the producer, and pipefail surfaces the 141.
#   * the listing's column layout, which varies between unzip builds.
# Extraction depends on none of them, and it additionally catches a member that
# exists but decompresses to garbage -- which no listing check can see.
extract_image() {
    local zip="$1" out="$2" cand
    for cand in Image.gz Image.lz4 Image; do
        case "$cand" in
            Image.gz)
                command -v gunzip >/dev/null 2>&1 || continue
                unzip -p "$zip" Image.gz  2>/dev/null | gunzip    > "$out" 2>/dev/null ;;
            Image.lz4)
                command -v lz4 >/dev/null 2>&1 || continue
                unzip -p "$zip" Image.lz4 2>/dev/null | lz4 -d -c > "$out" 2>/dev/null ;;
            Image)
                unzip -p "$zip" Image     2>/dev/null             > "$out" ;;
        esac
        # Status is ignored on purpose: a missing member makes unzip exit 11 and
        # write nothing, which image_ok rejects anyway.
        if image_ok "$out"; then printf '%s' "$cand"; return 0; fi
    done
    return 1
}

# resolve_kernel_asset <release-json> -- the wanted asset URL, or empty.
# Wants the KernelSU-Next root build WITHOUT charging bypass. The filtering is
# done in bash rather than with `... | head -1` so no producer can be SIGPIPEd.
resolve_kernel_asset() {
    local urls line lower
    urls="$(printf '%s' "$1" \
            | grep -o '"browser_download_url": *"[^"]*\.zip"' \
            | sed 's/.*"\(https[^"]*\)"/\1/')"
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        lower="${line,,}"
        case "$lower" in *kernelsu-next*) ;; *) continue ;; esac
        case "$lower" in *bypasscharging*) continue ;; esac
        printf '%s' "$line"; return 0
    done <<< "$urls"
    return 1
}

# stage_kernel <dest-file> -- fetch the release asset and write a raw arm64
# Image to <dest-file>.
stage_kernel() {
    local dest="$1"
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
    json="$(curl -fsSL "${auth[@]+"${auth[@]}"}" -H 'Accept: application/vnd.github+json' "$url")" \
        || { red "FATAL: cannot read $url"; return 1; }

    local asset
    if ! asset="$(resolve_kernel_asset "$json")" || [ -z "$asset" ]; then
        red "FATAL: no non-bypasscharging KernelSU-Next zip in that release."
        ylw "       assets present:"
        local all
        all="$(printf '%s' "$json" | grep -o '"name": *"[^"]*\.zip"')"
        printf '%s\n' "$all" | sed 's/^/         /'
        return 1
    fi

    ylw "   fetching $(basename "$asset")"
    local tmp; tmp="$(mktemp -d)"; _TMPS+=("$tmp")
    curl -fsSL "${auth[@]+"${auth[@]}"}" -o "$tmp/ak3.zip" "$asset" \
        || { red "FATAL: download failed"; return 1; }

    mkdir -p "$(dirname "$dest")"

    # Extract and validate in one step; see extract_image above for why this
    # does not look at a listing. The Image lands in scratch and is only moved
    # into place once it has passed, so a failure here cannot replace a
    # previously good staged Image with a stub.
    local src
    if ! src="$(extract_image "$tmp/ak3.zip" "$tmp/Image")"; then
        red "FATAL: no usable kernel Image could be extracted from the zip."
        ylw "       zip:   $(stat -c%s "$tmp/ak3.zip" 2>/dev/null) bytes, sha256 $(sha256sum "$tmp/ak3.zip" 2>/dev/null | cut -c1-16)"
        ylw "       unzip: $(unzip -v 2>/dev/null | head -1)"
        ylw "       tools: gunzip=$(command -v gunzip || echo MISSING) lz4=$(command -v lz4 || echo MISSING)"
        ylw "       members (diagnostic only -- not used for the decision):"
        printf '%s\n' "$(zip_names "$tmp/ak3.zip")" | sed 's/^/         /'
        return 1
    fi

    mv -f "$tmp/Image" "$dest" || { red "FATAL: cannot write $dest"; return 1; }
    local sz; sz="$(stat -c%s "$dest")"
    grn "   ++ $dest ($sz bytes, from $src, arm64 magic ok)"
}

# -------------------------------------------------------------------- preflight
# Everything checkable without a synced tree. The point is speed: crave's queue
# runs to hours, so a defect that only shows up on the build server costs a whole
# afternoon. Run this before submitting, and locally before pushing.
preflight() {
    local rc=0

    echo "== preflight 1/5: apply.sh parses"
    if bash -n "${BASH_SOURCE[0]}"; then grn "   ok"; else red "   !! syntax error"; rc=1; fi

    echo "== preflight 2/5: no early-exiting pipeline sits in a condition"
    # The bug that killed 295566. `grep -q`/`head` as the consumer of a pipeline
    # inside if/elif/while returns 141 under pipefail when the producer is still
    # writing. Catch a reintroduction here rather than on a build server.
    local offenders
    offenders="$(grep -nE '^[[:space:]]*(if|elif|while)[[:space:]].*\|[[:space:]]*(grep -q|head |head -|grep -m)' \
                 "${BASH_SOURCE[0]}" || true)"
    if [ -n "$offenders" ]; then
        red "   !! early-exiting pipeline used as a condition:"
        printf '%s\n' "$offenders" | sed 's/^/      /'
        rc=1
    else
        grn "   ok"
    fi

    echo "== preflight 3/5: patch set is structurally sound"
    local pdir key p n dirs=0 pats=0
    for pdir in "$HERE"/patches/*/; do
        [ -d "$pdir" ] || continue
        dirs=$((dirs+1))
        key="$(basename "$pdir")"
        if [ -z "${PROJECT[$key]:-}" ]; then
            red "   !! patches/$key has no PROJECT mapping (build would abort)"; rc=1
        fi
        local found=0
        for p in "$pdir"*.patch; do
            [ -e "$p" ] || continue
            found=1; pats=$((pats+1))
            if [ ! -s "$p" ]; then
                red "   !! $key/$(basename "$p") is empty"; rc=1; continue
            fi
            # --numstat parses the patch and reports what it would touch without
            # reading or writing the work tree, so it validates the file itself.
            if ! git apply --numstat "$p" >/dev/null 2>&1; then
                red "   !! $key/$(basename "$p") is not a well-formed diff"; rc=1
            fi
        done
        [ "$found" = 1 ] || { red "   !! patches/$key contains no .patch files"; rc=1; }
    done
    if [ "$dirs" = 0 ]; then red "   !! no patch directories at all"; rc=1; fi
    echo "   $pats patch file(s) across $dirs project dir(s)"

    # The Now Playing port is 53 files; gen-patches.sh asserts that on the way
    # out, so assert it on the way in too.
    local np="$HERE/patches/frameworks_base/0004-pixel-lockscreen-now-playing.patch"
    if [ -f "$np" ]; then
        n="$(grep -c '^diff --git ' "$np" || true)"
        if [ "$n" = 53 ]; then grn "   ok: Now Playing port touches 53 files"
        else red "   !! Now Playing port touches $n files, expected 53"; rc=1; fi
    fi

    echo "== preflight 4/5: OTA metadata template has what createjson.sh reads"
    local ota="$HERE/ota/crDroidOTA-$DEVICE.json"
    if [ ! -f "$ota" ]; then
        red "   !! $ota missing"; rc=1
    else
        # Keys createjson.sh's extract_field() pulls out. Several are legitimately
        # blank, so presence is the contract; the four that carry the unofficial
        # identity must also be non-empty.
        local k v
        for k in maintainer oem device buildtype forum gapps firmware modem \
                 bootloader recovery paypal telegram dt common-dt kernel; do
            if ! grep -q "\"$k\":" "$ota"; then
                red "   !! key \"$k\" absent -- createjson.sh would emit an empty field"; rc=1
            fi
        done
        for k in maintainer buildtype paypal device; do
            v="$(sed -n "s/.*\"$k\": *\"\([^\"]*\)\".*/\1/p" "$ota")"
            if [ -z "$v" ]; then red "   !! \"$k\" is empty"; rc=1
            else echo "   $k = $v"; fi
        done
        v="$(sed -n 's/.*"buildtype": *"\([^"]*\)".*/\1/p' "$ota")"
        [ "$v" = "Unofficial" ] || { red "   !! buildtype is '$v', expected 'Unofficial'"; rc=1; }
    fi

    echo "== preflight 5/5: kernel asset resolves AND an Image really comes out"
    if [ "${SKIP_KERNEL:-0}" = "1" ]; then
        ylw "   skipped (SKIP_KERNEL=1)"
    else
        local ktmp; ktmp="$(mktemp -d)"; _TMPS+=("$ktmp")
        if stage_kernel "$ktmp/Image"; then grn "   ok"; else red "   !! kernel staging would fail the build"; rc=1; fi
    fi

    echo
    if [ "$rc" -ne 0 ]; then
        red "PREFLIGHT FAILED - do not submit a build"
    else
        grn "preflight OK - safe to submit"
    fi
    return "$rc"
}

# ------------------------------------------------------------------- dispatch
if [ "$PREFLIGHT" = 1 ]; then
    preflight
    exit $?
fi

[ -d "$ROM/.repo" ] || { red "FATAL: $ROM is not a repo tree (no .repo)"; exit 1; }

apply_patches

if [ "${SKIP_FIRMWARE:-0}" != "1" ]; then
    echo "== firmware overlay"
    overlay_firmware || fail=1
fi

if [ "${SKIP_OTA_METADATA:-0}" != "1" ]; then
    echo "== OTA metadata overlay"
    overlay_ota_metadata || fail=1
fi

if [ "${SKIP_KERNEL:-0}" != "1" ]; then
    echo "== kernel"
    stage_kernel "$ROM/$KERNEL_DEST" || fail=1
fi

echo
echo "applied=$applied already-applied=$already"
if [ "$fail" -ne 0 ]; then
    red "PATCHING FAILED - not safe to build"
    exit 1
fi
grn "patch set OK"
