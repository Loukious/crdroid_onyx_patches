#!/usr/bin/env bash
# Run on the Crave BUILD WORKER from the Android source root, never devspace.
# No argument: configure the existing workspace, pin symbols, and prepare ABI.
# One argument: trace that ABI helper in the caller's configured environment.
# This script does not sync, install tools, or compile the full ROM.
set -u
set -o pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$PWD"
LOG_ROOT="$ROOT/abi-diagnostics"
mkdir -p "$LOG_ROOT" || exit 1
LOG_DIR="$(mktemp -d "$LOG_ROOT/run-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")" || exit 1
ARCHIVE="${LOG_DIR}.tar.gz"
monitor_pid=
run_pid=

phase() { printf '%s\n' "$*" > "$LOG_DIR/phase"; }

snapshot() {
    date -u +%FT%TZ
    cat /proc/loadavg /proc/meminfo
    df -h "$ROOT" /tmp
    df -i "$ROOT" /tmp
    # Root cgroup works in cgroup namespaces. Also inspect the process's path
    # when the worker exposes the host cgroup tree instead.
    local cgpath base file
    cgpath="$(sed -n 's/^0:://p' /proc/self/cgroup)"
    for base in /sys/fs/cgroup "/sys/fs/cgroup${cgpath}"; do
        for file in memory.events memory.current memory.peak memory.max pids.events pids.current pids.max cpu.stat; do
            if [ -r "$base/$file" ]; then
                printf '\n%s\n' "$base/$file"
                cat "$base/$file"
            fi
        done
    done
    for file in /proc/pressure/{cpu,memory,io}; do
        [ ! -r "$file" ] || { printf '\n%s\n' "$file"; cat "$file"; }
    done
    return 0
}

finish() {
    local rc=$?
    trap - EXIT HUP INT TERM
    if [ -n "$run_pid" ] && kill -0 "$run_pid" 2>/dev/null; then
        # GNU timeout creates a process group for itself and the helper.
        kill -TERM -- "-$run_pid" 2>/dev/null || kill -TERM "$run_pid" 2>/dev/null || true
    fi
    if [ -n "$monitor_pid" ]; then
        kill "$monitor_pid" 2>/dev/null || true
        wait "$monitor_pid" 2>/dev/null || true
    fi
    printf '%s\n' "$rc" > "$LOG_DIR/exit-code"
    snapshot > "$LOG_DIR/resources-after.txt" 2>&1
    {
        printf 'exit_code=%s\n' "$rc"
        printf 'last_phase=%s\n' "$(cat "$LOG_DIR/phase")"
        printf 'finished_utc=%s\n' "$(date -u +%FT%TZ)"
        printf 'archive=%s\n' "$ARCHIVE"
    } > "$LOG_DIR/result.txt"
    local file
    for file in .symvers-pin .prepared out/.config out/include/config/kernel.release; do
        if [ -f "kernel/xiaomi/konoha-abi/$file" ]; then
            mkdir -p "$LOG_DIR/abi-state/$(dirname "$file")"
            cp "kernel/xiaomi/konoha-abi/$file" "$LOG_DIR/abi-state/$file"
        fi
    done
    tar -czf "$ARCHIVE" -C "$LOG_ROOT" "$(basename "$LOG_DIR")"
    local archive_rc=$?
    printf '\nABI preparation result:\n' || true
    cat "$LOG_DIR/result.txt" || true
    if [ "$rc" -ne 0 ]; then
        tail -n 60 "$LOG_DIR/stderr.log" "$LOG_DIR/bash-xtrace.log" 2>/dev/null || true
    fi
    if [ "$archive_rc" -ne 0 ]; then
        echo "WARNING: archive creation failed; raw traces remain in $LOG_DIR" >&2
        [ "$rc" -ne 0 ] || rc=$archive_rc
    fi
    exit "$rc"
}
trap finish EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
phase 'collecting worker information'
# Record the parent's original streams before redirecting preparation output.
for fd in 0 1 2; do
    cat "/proc/$$/fdinfo/$fd" > "$LOG_DIR/inherited-fd-$fd.txt" 2>&1
    readlink "/proc/$$/fd/$fd" >> "$LOG_DIR/inherited-fd-$fd.txt" 2>&1
done
{
    uname -a
    cat /etc/os-release
    nproc
    ulimit -a
    readlink -f /bin/sh
    command -v make
    make --version
    bash --version
    git -C "$HERE" rev-parse HEAD
    git -C kernel/xiaomi/konoha-abi/src rev-parse HEAD
    git -C kernel/xiaomi/konoha-abi/src status --short
} > "$LOG_DIR/worker.txt" 2>&1
snapshot > "$LOG_DIR/resources-before.txt" 2>&1
owner_pid=$BASHPID
(
    trap - EXIT HUP INT TERM
    while kill -0 "$owner_pid" 2>/dev/null; do snapshot; sleep 10; done
) > "$LOG_DIR/resources-periodic.txt" 2>&1 &
monitor_pid=$!

prepare() {
    # Android envsetup/breakfast do not support strict-shell options.
    set +u
    set +o pipefail
    if [ "$#" -eq 0 ]; then
        phase 'environment setup'
        source build/envsetup.sh || return $?
        phase 'breakfast'
        breakfast "${DEVICE:-onyx}" userdebug || return $?
        phase 'pinning kernel symbols'
        source "$HERE/pin-konoha-symvers.sh" || return $?
    fi
    local prep="${1:-kernel/xiaomi/sm8735-modules/qcom/opensource/wlan/qcacld-3.0/konoha-abi-prep.sh}"
    phase 'selecting ABI toolchain'
    [ -f "$prep" ] || { echo "Missing ABI helper: $prep" >&2; return 1; }
    if [ -z "${CLANG_PATH:-}" ]; then
        local clang_bin
        clang_bin="$(for d in prebuilts/clang/host/linux-x86/clang-*/bin; do
            [ ! -x "$d/clang" ] || printf '%s\n' "$d"
        done | sort -V | tail -1)"
        [ -n "$clang_bin" ] || { echo 'No Android clang found' >&2; return 1; }
        CLANG_PATH="$ROOT/$clang_bin"
    fi
    export CLANG_PATH
    export PATH="$CLANG_PATH:$PATH"
    {
        command -v make sh bash clang
        clang --version
        printf 'PATH=%s\nTMPDIR=%s\nMAKEFLAGS=%s\n' "$PATH" "${TMPDIR-}" "${MAKEFLAGS-}"
        sha256sum "$prep"
    } > "$LOG_DIR/configured-tools.txt" 2>&1
    cp "$prep" "$LOG_DIR/prep-at-run.sh" || return $?
    if [ -f kernel/xiaomi/konoha-abi/.prepared ]; then
        echo 'ABI cache is stamped; helper will validate it and may skip compilation.'
    fi
    # Preserve the original Make recipe shell; PS4 must also parse under sh.
    export MAKEFLAGS="${MAKEFLAGS-} --trace V=1 .SHELLFLAGS=-xc"
    export PS4='+ ${EPOCHREALTIME:-no-clock} pid=${BASHPID:-$$} ${BASH_SOURCE:-sh}:${LINENO:-unknown}: '
    export BASH_ENV="$HERE/crave-abi-trace-env.sh"
    exec 9>>"$LOG_DIR/bash-xtrace.log"
    export BASH_XTRACEFD=9
    phase 'ABI preparation'
    timeout --kill-after=15s "${ABI_TRACE_TIMEOUT:-1h}" bash -x "$prep" &
    run_pid=$!
    wait "$run_pid"
    local rc=$?
    run_pid=
    printf '%s\n' "$rc" > "$LOG_DIR/preparation-exit-code"
    phase 'ABI preparation finished'
    return "$rc"
}

printf 'ABI trace directory: %s\n' "$LOG_DIR" || true
prepare "$@" > "$LOG_DIR/stdout.log" 2> "$LOG_DIR/stderr.log"
exit "$?"
