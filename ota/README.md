# Runtime OTA feed

`onyx.json` is what the in-ROM Updater fetches at runtime. It is served straight
from this repo over `raw.githubusercontent.com`, and
`patches/packages_apps_Updater/0001-self-hosted-ota-url.patch` is what points
the app here:

```
https://raw.githubusercontent.com/Loukious/crdroid_onyx_patches/evolution-cnb-onyx618/ota/{device}.json
```

## Why it exists

The point is to own the URL. Evolution X does not publish onyx today --
`Evolution-X/OTA` has no `onyx.json`, so the stock URL is a 404 as things
stand. The day that changes, an unmodified Updater would offer an official Evo
weekly as an update to this build, and flashing it would take the local patch
set, the LHDC codec and the Kono-Ha kernel with it. Pointing at a file we
control means that can never happen by accident.

## Published feed and default branch (2026-11-18)

The default patches branch is now `evolution-cnb-onyx618`. Its feed and changelog
preserve the exact published contents from `evolution-cnb` commit `ad7da3b`,
including the November 13, 15 and 16 Android 17 releases. The active Updater
patch fetches this new branch.

Future publication jobs must target `evolution-cnb-onyx618`. External dated
publication runners and workflows that still pin `evolution-cnb` require a
separate update before publishing to the new default branch. The existing
`evolution-cnb` and `evolution-bka` feeds remain available for already installed
ROMs that use those URLs; changing this source patch takes effect in a rebuilt
Updater/ROM.

The publish step historically ran in `Loukious/crave_aosp_builder`'s
`crdroid-onyx.yml` workflow: after a build's zip lands on SourceForge, it commits
one entry per build, newest first. Every entry's `download` URL points at the
SourceForge `/download` link, same pattern crDroid's own OTA feed uses. The
Updater's parser (`org.evolution.updater.misc.Utils.parseJsonUpdate`)
getString()s nine fields per entry -- timestamp, filename, md5, size,
download, version, maintainer, forum, firmware, paypal -- all of which every
entry carries. `timestamp` is the zip's `post-timestamp` from
`META-INF/com/android/metadata` (= `ro.build.date.utc`), which is exactly
what `Utils.isCompatible()` compares against, so each new build sorts as
newer than the previous one.

The `crdroid-16.0` branch copy stays `{"response": []}` -- any old crDroid ROM
pointing there simply sees "no updates", which is correct (those builds are
superseded).

Do not hand-edit `onyx.json` to add a build: the next CI publish would race
the hand edit. Hand edits are fine for removing stale entries.

## This is not the old crDroid metadata

The crDroid tree had a *build-time* file, `vendor/crDroidOTA/<device>.json`,
that `createjson.sh` read to stamp the maintainer, donate URL and build type
into the release. `apply.sh` used to overlay a template over it. Evolution X has
no `vendor/crDroidOTA` and no equivalent -- `vendor_evolution/build/tools/createjson.py`
takes the maintainer name from its own server-side data -- so that overlay, its
template and its preflight check were all removed. What is left in this
directory is only the runtime feed described above.
