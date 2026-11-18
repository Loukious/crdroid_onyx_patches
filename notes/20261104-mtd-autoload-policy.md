# Onyx MTD archive autoload policy

Device patch `0018-allow-modprobe-mtd-block-path.patch` creates
`device/xiaomi/onyx/sepolicy/vendor/vendor_modprobe.te` with one rule:

```te
allow vendor_modprobe block_device:dir search;
```

The first MTD installation booted Android normally with the MTD core, logger
and pmsg mapping present. Automatic attachment of the block-backed adapter
failed with `-EACCES` (`-13`). Its boot parameter selects the existing backing
partition: `block2mtd.block2mtd=/dev/block/by-name/oops,2097152,0`.

The exact relevant AVC, with terminal colour escapes removed, is:

```text
[    4.744382] type=1400 audit(14715.747:12): avc:  denied  { search } for  comm="modprobe" name="block" dev="tmpfs" ino=12 scontext=u:r:vendor_modprobe:s0 tcontext=u:object_r:block_device:s0 tclass=dir permissive=0
```

Evidence: `install-20261104T153714Z/dmesg-attach-failure.txt` under
`/home/loukious/Android/konoha-priority-ports-20261103/mtd-persistence-port`.
The complete captured file has SHA-256
`d020e8507b62e750b0d2c920bc518f4240f81689fdf04530ee406cbd8978ec62`.

The native adapter calls `bdev_file_open_by_path()` during module initialization.
Linux 6.18 implements that as `lookup_bdev()` followed by the kernel block-device
open. `lookup_bdev()` first calls `kern_path(..., LOOKUP_FOLLOW, ...)`, so the
path walk inherits the loading task's `vendor_modprobe` context and checks
directory search. The denial occurs while traversing `/dev/block`, before the
backing device can be resolved.

The rule permits traversal of directories labelled `block_device`, including
`/dev/block`. It grants neither directory listing nor raw block-node
`blk_file` open/read/write permissions. Existing userspace raw block-access
policy remains in force. No permissive domain, credential override or loader
change is part of this patch.

The retained logger archives normal reboot, poweroff and long power-key events.
Its native panic/oops callback remains inactive. Automatic attachment on the
installed ROM remains pending a ROM build and installation containing this
policy; a temporary live-policy test does not make the ROM change persistent.

The patch and source file are identical. Forward application, reverse
application and the existing reverse-check skip convention were verified in an
isolated Git checkout. The current source passes a reverse check, and
`gen-patches.sh` passes `bash -n`. Full patch application/generation and a full
ROM build were not run. Existing device changes and patch `0017` were retained.

Targeted host SELinux validation also passed. All ten existing Onyx split
CIL/mapping/genfs inputs compiled with neverallow checks enabled and a
versioned-equivalent overlay of this rule. The decompiled effective policy
changed only by adding `vendor_modprobe` directory search on `block_device`;
no rules were removed and permissive domains stayed unchanged. A mutation
granting raw block-node read/write was rejected by the neverallow at
`system/sepolicy/private/domain.te:757`.

The receipt is `rom-policy-validation/targeted-policy-validation.json` under
the MTD port directory above, SHA-256
`24f0d002197f105e29b0f00bc5d1b4174c412428497517d8c04970168e492b5c`.
This verifies the rule against the existing compiled policy inputs; fresh TE
generation and the complete ROM build remain pending.
