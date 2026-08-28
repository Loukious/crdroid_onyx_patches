# Runtime OTA feed

`onyx.json` is what the in-ROM Updater fetches at runtime. It is served straight
from this repo over `raw.githubusercontent.com`, and
`patches/packages_apps_Updater/0001-self-hosted-ota-url.patch` is what points
the app here:

```
https://raw.githubusercontent.com/Loukious/crdroid_onyx_patches/evolution-bka/ota/{device}.json
```

## Why it exists

Nothing here publishes builds, so the honest answer is "no updates available",
and `{"response": []}` is exactly how Evolution X's Updater says that:
`Utils.parseJson()` reads `obj.getJSONArray("response")` and iterates it, so an
empty array parses cleanly and yields zero updates. A 404 or a malformed file
would surface as an error toast instead.

The point is to own the URL. Evolution X does not publish onyx today --
`Evolution-X/OTA` has no `onyx.json`, so the stock URL is a 404 as things
stand. The day that changes, an unmodified Updater would offer an official Evo
weekly as an update to this build, and flashing it would take the local patch
set, the LHDC codec and the Kono-Ha kernel with it. Pointing at a file we
control means that can never happen by accident.

## This is not the old crDroid metadata

The crDroid tree had a *build-time* file, `vendor/crDroidOTA/<device>.json`,
that `createjson.sh` read to stamp the maintainer, donate URL and build type
into the release. `apply.sh` used to overlay a template over it. Evolution X has
no `vendor/crDroidOTA` and no equivalent -- `vendor_evolution/build/tools/createjson.py`
takes the maintainer name from its own server-side data -- so that overlay, its
template and its preflight check were all removed. What is left in this
directory is only the runtime feed described above.
