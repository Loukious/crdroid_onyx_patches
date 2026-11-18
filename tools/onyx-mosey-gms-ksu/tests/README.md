# Android 17 output contracts

The user-state contract was checked on the connected Onyx phone on 2026-11-17:
`/system/bin/cmd activity get-started-user-state 0` returned exactly
`RUNNING_UNLOCKED`. The same `am` command works. `cmd user is-user-unlocked`
is unsupported. The framework's `ActivityManagerShellCommand.runGetStartedUserState`
also declares and prints this API.

The service fixture preserves the observed provider/delegate record structure,
app process/PID fields, `isForeground` and `isFgsDelegate` fields. Record IDs are
anonymized. Negative fixtures are derived by removing a record-local process,
changing its PID, or placing a live process in an unrelated record.

The complete provider startup regression must also execute with real `mksh`,
the shell behind Android `/system/bin/sh`. Host `/bin/sh` alone missed the
revision 3 bug: unescaped `|` in `${pids%%|*}` / `${pids#*|}` is alternation
in mksh, so a matching pair became an empty provider PID and an unsplit delegate
PID. Revision 4 uses `:` and checks matching records, missing processes,
different live PIDs, foreground/delegate flags, bounded polling and a single
delegate request. Install a host `mksh`, or set `MOSEY_TEST_MKSH` to a real
executable extracted from the distribution package. Tests reject a missing mksh.
