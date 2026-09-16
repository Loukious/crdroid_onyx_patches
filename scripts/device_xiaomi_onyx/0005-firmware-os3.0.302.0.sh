#!/usr/bin/env bash
# Update the firmware provenance comment from OS3.0.7.0 to OS3.0.302.0.
# Content-matched so it survives any reordering of the file.
set -euo pipefail
proj="$1"
file="$proj/proprietary-firmware.txt"
if [ ! -f "$file" ]; then echo "   !! $file not found"; exit 1; fi
if grep -q 'OS3.0.302.0' "$file"; then
    echo "   -- firmware comment already at OS3.0.302.0"
    exit 0
fi
if ! grep -q 'OS3.0.7.0' "$file"; then
    echo "   -- firmware comment does not mention OS3.0.7.0 (nothing to do)"
    exit 0
fi
sed -i 's/OS3\.0\.7\.0/OS3.0.302.0/g' "$file"
echo "   ++ updated firmware comment to OS3.0.302.0"
