#!/usr/bin/env bash
# Select the Onyx source recipe after sync and stage the ROM build adapter.
set -euo pipefail
[ "${KONOHA_SOURCE_BUILD:-1}" = 1 ] || exit 0
python3 - "$1" <<'PY'
import json
from pathlib import Path
import re
import sys
p=Path(sys.argv[1]);board=p/'BoardConfig.mk'
s=board.read_text()
if '# Onyx source-built Kleaf boot configuration' not in s:
    marker='# Kernel\n' if '# Kernel\n' in s else '# Konoha matched prebuilt boot configuration\n'
    start=s.index(marker);end=s.index('# Partitions\n',start)
    old=s[start:end]
    def assignment(name):
        lines=old.splitlines();i=next(i for i,l in enumerate(lines) if l.startswith(name+' :='));result=[]
        while True:
            line=lines[i];result.append(line);i+=1
            if not line.rstrip().endswith('\\'):return '\n'.join(result)+'\n'
    block='''# Onyx source-built Kleaf boot configuration
BOARD_INCLUDE_DTB_IN_BOOTIMG := true
BOARD_RAMDISK_USE_LZ4 := true
TARGET_NEEDS_DTBOIMAGE := true
BOARD_KERNEL_BASE := 0x00000000
BOARD_KERNEL_PAGESIZE := 4096
BOARD_KERNEL_IMAGE_NAME := Image
BOARD_BOOT_HEADER_VERSION := 4
BOARD_MKBOOTIMG_ARGS := --header_version $(BOARD_BOOT_HEADER_VERSION)
BOARD_INIT_BOOT_HEADER_VERSION := 4
BOARD_MKBOOTIMG_INIT_ARGS += --header_version $(BOARD_INIT_BOOT_HEADER_VERSION)
'''+assignment('BOARD_KERNEL_CMDLINE')+'\n'+assignment('BOARD_BOOTCONFIG')+'\n'
    s=s[:start]+block+s[end:]
# Remove legacy Image-only hooks, including duplicate hooks from older patch runs.
s=s.replace('# Custom prebuilt kernel\n', '')
s=s.replace('# CFR streamfs uses relay exports. The source-built kernel also supplies the\n# System.map used to validate vendor modules before packing the Kono-Ha ROM.\n', '')
s=re.sub(r'(?m)^-?include vendor/extra/BoardConfigKernel\.mk\n?','',s)
s=re.sub(r'(?m)^TARGET_KERNEL_CONFIG_EXT \+= device/xiaomi/onyx/configs/wifi/cfr-kernel\.config\n?','',s)
s=re.sub(r'(?m)^# Matched kernel, modules and device trees, after all vendor configuration\.\n?','',s)
s=re.sub(r'(?m)^include device/xiaomi/onyx-kernel/BoardConfig\.mk\n?','',s)
s=re.sub(r'(?m)^include device/xiaomi/onyx/build/konoha/BoardConfig\.mk\n?','',s)
s=re.sub(r'(?m)^include kernel/platform/kernel-6\.18/port/rom/BoardConfig\.mk\n*','',s)
s=s.replace('# Partitions\n','include kernel/platform/kernel-6.18/port/rom/BoardConfig.mk\n\n# Partitions\n',1)
s=s.rstrip()+'\n\n# Matched kernel, modules and device trees, after all vendor configuration.\ninclude kernel/platform/kernel-6.18/port/rom/BoardConfig.mk\n'
if 'kernel/xiaomi/sm8735' in s:raise SystemExit('Unexpected remaining source-kernel reference')
board.write_text(s)
for dep in p.glob('*.dependencies'):
    data=json.loads(dep.read_text())
    filtered=[e for e in data if e.get('target_path') not in {'kernel/xiaomi/sm8735','kernel/xiaomi/sm8735-modules','kernel/xiaomi/sm8735-devicetrees','kernel/xiaomi/onyx-wlan'}]
    if filtered!=data:dep.write_text(json.dumps(filtered,indent=2)+'\n')
print('   ++ Onyx builds its synced GKI and modules through the Kleaf source recipe')
PY
