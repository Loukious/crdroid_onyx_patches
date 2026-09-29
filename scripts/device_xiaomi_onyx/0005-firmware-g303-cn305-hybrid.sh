#!/usr/bin/env bash
# Update the firmware provenance comment to the G303 + CN305 modem hybrid.
# Content-matched so it survives any reordering of the file.
set -euo pipefail
proj="$1"
file="$proj/proprietary-firmware.txt"
if [ ! -f "$file" ]; then echo "   !! $file not found"; exit 1; fi
want='# Firmware: OS3.0.303.0.WOLMIXM, except modem.img/modemfirmware.img from OS3.0.305.0.WOLCNXM'
if grep -Fqx "$want" "$file"; then
    echo "   -- firmware comment already at G303/CN305 hybrid"
    exit 0
fi
python3 - "$file" "$want" <<'PY'
from pathlib import Path
import re, sys
p=Path(sys.argv[1]); want=sys.argv[2]
s=p.read_text()
s2,n=re.subn(r'^# .*firmware.*$', want, s, count=1, flags=re.M|re.I)
if n != 1:
    raise SystemExit('could not find firmware provenance comment')
p.write_text(s2)
PY
echo "   ++ updated firmware comment to G303/CN305 hybrid"
