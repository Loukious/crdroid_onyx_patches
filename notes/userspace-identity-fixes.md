The phone logs identified two failures in Evolution's userspace code:

- PermissionController could not open the installed Lineage resource APK
  during permission backup. Evolution's bionic hiding classified its app-range
  UID as a filtering client. Patch `bionic/0001` adds only
  `com.android.permissioncontroller` to the existing exemption list.
- TrickyStore configuration refresh threw `INTERACT_ACROSS_USERS` because
  `canReadTrickyStoreKeybox()` queried the foreground user under the incoming
  app Binder identity. Patch `frameworks_base/0011` scopes identity clearing to
  that query. The saved caller UID and all user, package, target and SKIP checks
  remain in place; Binder identity is restored in `finally` before package
  authorization continues.

Both patches require a rebuilt and installed ROM. They do not modify SELinux
policy or give applications cross-user permissions.

`apply.sh` uses `ci/upstream_fix_state.py` for these two patches. An exemption
already present in bionic is skipped even if neighboring upstream entries
changed. TrickyStore is skipped when its old implementation was removed, when
the direct `ActivityManager.getCurrentUser()` call was replaced (for example
by `ActivityManagerInternal`), or when that call already uses a recognized
scoped Binder identity idiom. The scoped check is confined to the authorization
method: the pre-existing clear around key retrieval does not qualify. Comments,
string literals, an identity restored before the query, and a mismatched restore
token do not qualify either.

Needed patches use exact `git apply` checks. A patch conflict is never silently
converted into "fixed upstream". A future rewrite that still contains an
unrecognized direct user query can require review; arbitrary future source
changes cannot be proven correct by this detector. The generator retains the
carried patch when source HEAD has an upstream replacement, so regeneration
does not fail on an empty diff or undo that replacement.

Guard and patch-runner regression cases run in `apply.sh --preflight`:

```sh
python3 -B -m unittest discover -s ci/tests -p test_upstream_fixes.py -v
```

The tests exercise the actual patch runner in isolated minimal ROM trees,
including repeated application, differently implemented upstream fixes,
removed methods and genuine unresolved conflicts. All 18 cases passed on
2026-11-07, including retaining the patches when regeneration sees an
upstream fix in HEAD.

The production authorization method and bionic process-classification functions
were also extracted from isolated copies and compiled in host harnesses:

- Bionic baseline: the three PermissionController cases fail; the patched
  version passes all 11 cases. Exact package matching, subprocess names,
  secondary users, ordinary app filtering and the existing updater exemption
  are covered.
- TrickyStore baseline: 16 app cases fail with the modeled cross-user
  permission exception; the two privileged-caller cases pass. The patched
  method passes all 18 cases, including owner/foreground/background users,
  untargeted apps, shared-UID exclusions, JSON and legacy SKIP entries, and
  identity restoration when either lookup throws. JSON parsing uses Android's
  `org.json` implementation from an android-all test jar.

To run those checks against a separate patched checkout:

```sh
ONYX_USERSPACE_TEST_ROM=/path/to/isolated/rom \
ONYX_ANDROID_TEST_JAR=/path/to/android-all.jar \
python3 -B -m unittest discover -s ci/tests -p test_userspace_behavior.py -v
```

The complete 63-patch preflight passed. Both new patches reverse-check and
regenerate byte-for-byte. The kernel-download check is skipped by this source
build branch. These are isolated host compilation, behavior and patch-application
checks; they do not represent a new full ROM build or a device deployment.
