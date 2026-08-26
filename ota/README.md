# OTA index

`packages/apps/Updater` on these builds points here instead of at crDroid's
official index:

```
https://raw.githubusercontent.com/Loukious/crdroid_onyx_patches/crdroid-16.0/ota/{device}.json
```

(see `patches/packages_apps_Updater/0001-self-hosted-ota-url.patch`).

`onyx` **has** official crDroid support. Left pointing upstream, the Updater
would offer the official weekly as an update to an unofficial build and flash
away the entire patch set, the PixelOS GApps and the Kono-Ha kernel. An empty
`response` array is the safe state: the app reports "no updates" rather than
erroring.

## Publishing a real update here

`vendor/lineage/build/tools/createjson.sh` already emits exactly this schema at
`bacon` time, with the real timestamp, size, md5 and sha256 of the zip it just
built, and it takes the maintainer / buildtype / donate fields from
`vendor/crDroidOTA/onyx.json` (which
`patches/vendor_crDroidOTA/0001-unofficial-ota-metadata.patch` rewrites for this
build). So publishing is: `crave pull out/target/product/onyx/onyx.json`, fix
the `download` field, and commit it over this file.

The `download` field is the one thing that is *not* right out of the box —
createjson.sh hardcodes a SourceForge path. A GitHub release asset needs the
release tag, which createjson.sh has no way to know, and
`releases/latest/download/...` cannot be used because the Updater's OkHttp
client is built with `followRedirects(false)`. So it has to be rewritten in CI
against the tag the workflow just created.
