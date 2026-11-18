# Serial first-stage module loading

This note records an earlier diagnostic checkpoint. The serial-loading patch
and the later `system/core` loader patch were removed at the user's request.
Commit `e9e0b7d` was removed from `evolution-cnb` history; its branch tip is
`08d7297`. Neither patch is available for application in this checkout.
The WALT/hung-task kernel fix remains published separately. Validation with
the original ROM loaders is recorded in the kernel repository's
`port/parallel-module-loading.md`.

The removed patch `0019-use-serial-first-stage-module-loading.patch`
changed only the `BoardConfig.mk` bootconfig property
`androidboot.load_modules_parallel=true` to `false`. At that checkpoint it made
future ROM builds use serial first-stage module loading with the 6.18 port.

The original EvolutionX boot image enabled parallel loading. Both attempts to
enter fastbootd stalled at the POCO splash with no ADB or fastboot connection.
After a temporary vendor_boot image changed only this property to `false`,
with its original modules and DTB retained and the verified recovery bridge
installed, `fastboot reboot fastboot` reached userspace fastboot successfully.
This supported serial loading at that checkpoint; it does not identify the
cause of the original runtime crash.

The earlier matched package combined the serial setting with the AW/SIA probe
fixes. Its vendor_boot image retains the verified module ramdisk and DTB,
changes one bootconfig value, and preserves the existing AVB settings. Final
installation and readback acceptance passed later on November 5. All nine
partition hashes matched the final manifest, both AW/SIA live module IDs matched
the rebuilt files, and the retained GKI/KernelSU were verified. Two fresh boots
registered both AW amplifiers and the sound card automatically; Android reached
boot completion by 22.24 and 20.62 seconds. Audio/system services were healthy at
156.81 seconds on the first boot and 92.35 seconds on the second. The final
recovery reached fastbootd and the phone returned to Android. A complete ROM
rebuild was not run. The removed producer patch was intended to persist this
flag in future ROM builds. These combined-image tests do not isolate the flag from the amplifier
fixes, and do not resolve the original spontaneous crash.

Forward application, reverse application, and the existing reverse-check skip
convention passed on an isolated copy of the current dirty BoardConfig.mk.
The live device project and its existing changes were left intact. Private
validation: `konoha-audio-fix-install-20261105/rom-serial-patch-validation/report.json`.
Device evidence: `serial-bridge-fastbootd-transition.json` and
`package-v4/report.json` in the same installation directory.
