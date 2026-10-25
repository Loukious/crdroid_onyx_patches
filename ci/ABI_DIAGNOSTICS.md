# Crave ABI preparation diagnostics

`crave-build.sh` runs `crave-abi-trace.sh` around Kono-Ha ABI preparation.
All commands live in this repository as ordinary shell source. There are no
encoded payloads, downloaded executables, tool installations, or syscall probes.
This diagnostic does not change ROM code.

The wrapper saves stdout and stderr directly to regular files, enables Bash
command and error tracing, and enables recursive Make command/recipe tracing
without replacing the recipe shell. It also records compiler and shell
versions, source revision, original stream flags, resource limits, free space
and inodes, memory pressure, and cgroup memory/process-limit events before,
during, and after preparation. It does not dump the complete environment.

Each invocation creates a unique `abi-diagnostics/run-*.tar.gz`, with the raw
logs alongside it. `result.txt`, `exit-code`, and `preparation-exit-code` record
the outcome; the wrapper returns the actual failing status to the build.
Setup failures also produce an archive. A one-hour timeout returns status 124;
`ABI_TRACE_TIMEOUT` can override this GNU timeout duration. A host crash,
SIGKILL, or full/unavailable storage can prevent final archive creation.

To diagnose an existing failed workspace without syncing or compiling the ROM,
submit this readable command from the normal Crave devspace project directory:

```sh
crave -n run --projectID 99 --no-patch --disable-build-cache \
  --artifacts 'abi-diagnostics/*.tar.gz' -- \
  'git clone --depth 1 --branch evolution-cnb https://github.com/Loukious/crdroid_onyx_patches /tmp/onyx-abi-diagnostics-recipe && bash /tmp/onyx-abi-diagnostics-recipe/ci/crave-abi-trace.sh'
```

Use a fresh checkout directory if that `/tmp` path already exists. The script
runs **on the build worker**, not in devspace. It uses the existing workspace,
runs environment setup and breakfast, pins the staged kernel symbols, then
prepares only the ABI. It does not remove a valid cache stamp to force a rebuild;
the logs explicitly report when the helper may take its cache-validation path.

The ordinary full-build workflow also records the traces automatically. Its
existing `--no-artifacts` option does not automatically retrieve them; use the
diagnostic command above when automatic trace retrieval is needed. On failure,
the wrapper prints the result, archive path, and the last trace lines into the
Crave log as well. These traces investigate any ABI-stage failure, not just the
suspected output-stream failure; they do not prove a root cause on their own.
