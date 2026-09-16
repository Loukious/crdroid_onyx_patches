#!/usr/bin/env bash
# Remove GoogleDialer from the GMS full package list so the build ships the AOSP
# dialer instead.  Written as a content-matching script rather than a positional
# patch so it survives upstream line-number drift in gms_full.mk.
set -euo pipefail
proj="$1"
file="$proj/gms_full.mk"
if [ ! -f "$file" ]; then echo "   !! $file not found"; exit 1; fi
if ! grep -q 'GoogleDialer' "$file"; then
    echo "   -- GoogleDialer already absent"
    exit 0
fi
sed -i '/^[[:space:]]*GoogleDialer[[:space:]]*\\/d' "$file"
echo "   ++ removed GoogleDialer from gms_full.mk"
