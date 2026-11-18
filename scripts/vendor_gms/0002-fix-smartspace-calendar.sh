#!/usr/bin/env bash
set -euo pipefail

project_dir="${1:?usage: 0002-fix-smartspace-calendar.sh /path/to/vendor/gms}"
patches_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
helper_dir="$patches_dir/tools/onyx-smartspace-fix"
work_dir="$helper_dir/.work"
base_asset="$patches_dir/assets/onyx-smartspace/AndroidSystemIntelligence-C9.apk.xz"
prebuilt_dir="$project_dir/product/packages/privileged_apps/DevicePersonalizationAiAiPrebuiltPixel2026"
prebuilt="$prebuilt_dir/DevicePersonalizationAiAiPrebuiltPixel2026.apk"
input_apk="$work_dir/AndroidSystemIntelligence-C9.original.apk"
output_apk="$work_dir/AndroidSystemIntelligence-C9-onyx.apk"
stamp="$work_dir/applied-inputs.txt"

[[ -f "$prebuilt" && -f "$base_asset" && -f "$helper_dir/build-rom.py" ]] || {
    printf 'Missing At a Glance source, builder, or GMS prebuilt.\n' >&2
    exit 1
}
rg -q '^LOCAL_CERTIFICATE := PRESIGNED$' "$prebuilt_dir/Android.mk"
rg -q '^LOCAL_SDK_VERSION := 37$' "$prebuilt_dir/Android.mk" || {
    printf 'Apply 0002-preserve-smartspace-prebuilt.patch before the calendar script.\n' >&2
    exit 1
}
mkdir -p "$work_dir"

fingerprint="$(python3 - "$helper_dir" "$base_asset" "${BASH_SOURCE[0]}" <<'PY'
import hashlib
from pathlib import Path
import sys
helper, asset, script = map(Path, sys.argv[1:])
digest = hashlib.sha256()
for path in [helper/'build-rom.py', *sorted((helper/'src').rglob('*.java')), asset, script]:
    digest.update(path.name.encode() + b'\0')
    with path.open('rb') as stream:
        while chunk := stream.read(1048576): digest.update(chunk)
print(digest.hexdigest())
PY
)"
current_hash="$(sha256sum "$prebuilt")"
current_hash="${current_hash%% *}"
previous_fingerprint=''
previous_output=''
if [[ -f "$stamp" ]]; then
    mapfile -t saved < "$stamp"
    previous_fingerprint="${saved[0]:-}"
    previous_output="${saved[1]:-}"
fi
if [[ "$fingerprint" = "$previous_fingerprint" && "$current_hash" = "$previous_output" ]]; then
    printf 'At a Glance calendar correction is already applied.\n'
    exit 0
fi
case "$current_hash" in
    8371170e6b80c2ce842592171bce7d65f8aeaeae78955bb414517d6883109f2c|417c0a7aa18f7c54174bba33bf02fba623ead200f4a54cd0ce66c57d6c8fdc1a|3c3d21f9618fd25db7ce8b25953e9d6e35634ee615b1035b5b3bf068b2dbca73) ;;
    *)
        [[ -n "$previous_output" && "$current_hash" = "$previous_output" ]] || {
            printf 'Unexamined AIAI prebuilt %s; review it before updating the calendar patch.\n' "$current_hash" >&2
            exit 1
        }
        ;;
esac
if [[ ! -f "$input_apk" ]]; then
    xz --decompress --stdout "$base_asset" > "$input_apk.next"
    mv -- "$input_apk.next" "$input_apk"
fi
printf '%s  %s\n' '417c0a7aa18f7c54174bba33bf02fba623ead200f4a54cd0ce66c57d6c8fdc1a' "$input_apk" | sha256sum --check --status
python3 "$helper_dir/build-rom.py" "$input_apk" "$work_dir/build" --output "$output_apk"
output_hash="$(sha256sum "$output_apk")"
output_hash="${output_hash%% *}"
install -m 644 "$output_apk" "$prebuilt.next"
mv -- "$prebuilt.next" "$prebuilt"
printf '%s\n%s\n' "$fingerprint" "$output_hash" > "$stamp.next"
mv -- "$stamp.next" "$stamp"
printf 'Installed the ROM At a Glance calendar prebuilt: %s\n' "$output_hash"
