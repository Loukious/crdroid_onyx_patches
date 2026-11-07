Onyx's selected prebuilt Qualcomm PAL and AGM libraries expect
`/vendor/etc/mem_logger_config.xml`, but the device did not install that file.
The phone logged repeated null-mutex calls and
`palStateQueueBuilder: queues failed to initialize` during audio operations.
Onyx patch `0023` adds the missing `PRODUCT_COPY_FILES` entry.

The configuration already exists at
`hardware/qcom-caf/sm8750/audio/primary-hal/configs/sun/mem_logger_config.xml`.
It is byte-for-byte identical to the 1,216-byte file extracted from both stock
Global `OS3.0.303.0.WOLMIXM` and China `OS3.0.305.0.WOLCNXM` images:

```
SHA-256 3e871bd2c6a1e15910f47e464f2e55d2440513afd2b3c9d494bfc56ab0a19b71
```

It defines the PAL state, KPI, graph and subsystem-reset queues and the graph
and subsystem-reset statistics buffers. Their definitions, limits and output
paths retain the stock values. Both stock images also carry the same
`libarmemlog.so` as the selected vendor prebuilt.

The missing destination was confirmed by read-only ADB inspection as well as
the generated vendor file list. The audio service's existing init script
already creates `/data/vendor/audio/memlog` with mode 0770 and owner/group
`audio`; the phone has that directory with `vendor_audio_data_file` labeling.
The fix therefore needs no init, SELinux, audio-library or kernel change.

Validation applies the patch and checks its reverse on an isolated source
copy, resolves the new Makefile copy entry to the existing XML, checks all six
queue/stat-buffer definitions and stock hashes, and reproduces the patch with
the generator's actual hunk-selection helper. The patch repository's preflight
also checks the complete patch set. No full ROM rebuild or audio-service
restart is part of this validation; the user's independent build is untouched.

The configuration takes effect in a newly built and installed ROM. Runtime
verification should check that the file is present after installation and
that normal audio operations no longer emit these initialization errors.
This correction does not establish the cause of the separate DSP low-power
warnings or claim to fix them.
