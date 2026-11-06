#!/usr/bin/env bash
set -euo pipefail
[ "${KONOHA_SOURCE_BUILD:-1}" = 1 ] || exit 0
python3 - "$1" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])/'config/BoardConfigLineage.mk'
s=p.read_text()
lines=[l for l in s.splitlines(keepends=True) if not (l.startswith('BUILD_BROKEN_SRC_DIR_RW_ALLOWLIST +=') and ('kernel/xiaomi/sm8735' in l or 'kernel/xiaomi/konoha-abi' in l))]
p.write_text(''.join(lines))
print('   ++ removed legacy kernel source write allowlists')
PY
