# Unapplied

Patches kept for reference. **Nothing in this directory is applied by
`apply.sh`** — it only walks `patches/*/`, and the directory name here
deliberately maps to no git project.

That matters: `apply.sh` exits non-zero on a patch that does not apply, so a
non-applying patch dropped into `patches/frameworks_base/` would fail every
build. These live here instead.

## `evolution-x-1a9ae21-non-pixel-ambient-nowplaying.patch`

Evolution-X
[`1a9ae21`](https://github.com/Evolution-X/frameworks_base/commit/1a9ae21398dba8ba933b4c2e3feb2a4af4324d73),
"SystemUI: Add non-Pixel ambient Now Playing indicator, fall back to native on
Pixel" (2026-08-22).

**Not used, and not needed for Now Playing on `onyx`.** Two reasons.

### It is not ambient recognition

Despite the name, this commit does not recognise ambient music. Its own
`NowPlayingAmbientContainer` header says it is

> a non-Pixel, self-contained port of Google's `AmbientIndicationContainer`
> visual/animation language, driven entirely by `NowPlayingViewController`'s own
> **MediaSessionManager** data

— i.e. it renders the Pixel Now Playing *look* using whatever media session is
already playing locally. It engages only when
`PixelAmbientIndicationDetector.shouldUseNativeAmbientIndication()` returns
false, as a cosmetic fallback for devices that cannot get the real thing.

`onyx` can get the real thing: DPS (`com.google.android.as`) ships in the
PixelOS GApps and the Pixel gating features are installed, so
`patches/frameworks_base/0004-pixel-lockscreen-now-playing.patch` — the port of
Evolution-X `c83186b` — gives genuine ambient song recognition. This commit
would be a downgrade.

### It cannot apply to crDroid anyway

It is an incremental refactor of Evolution-X's own lockscreen Now Playing
stack, none of which exists in crDroid. `git apply --check` against crDroid
`frameworks/base`:

```
error: packages/SystemUI/res/values/evolution_dimens.xml: No such file or directory
error: .../systemui/nowplaying/NowPlayingExpandedOverlay.kt: No such file or directory
error: .../systemui/nowplaying/NowPlayingSettingsRepository.kt: No such file or directory
error: .../systemui/nowplaying/NowPlayingViewController.kt: No such file or directory
error: patch failed: .../keyguard/ui/view/layout/blueprints/DefaultKeyguardBlueprint.kt:36
error: patch failed: .../keyguard/ui/view/layout/sections/KeyguardSectionsModule.kt:30
error: patch failed: .../statusbar/phone/CentralSurfacesImpl.java:135
```

crDroid has no `com/android/systemui/nowplaying/` package at all; it ships its
own unrelated `axdynamicbar` (`ExpandedNowPlayingContent.kt`,
`PillIslandContent.kt`, `AxDynamicBarKeyguardChip.kt`) for on-screen media.

Landing this would mean first porting the nine Evolution-X commits that build
that stack, oldest first:

| commit | date | subject |
|---|---|---|
| `0f9d699c2` | 2025-11-16 | SystemUI: Introduce Lockscreen Now playing |
| `68f3c7839` | 2025-11-20 | SystemUI: Fix missing now playing callbacks |
| `90b11428b` | 2026-02-08 | SystemUI: Hide nowplaying view when bouncer is showing |
| `21e7e1946` | 2026-03-30 | SystemUI: Introduce nowplaying music dialog [1/2] |
| `e4355a5c0` | 2026-06-09 | SystemUI: Fix nowplaying visibility flicker and show logic |
| `a4f1b2f7c` | 2026-06-10 | SystemUI: Add album art color mode in nowplaying [1/2] |
| `beb406a73` | 2026-07-20 | SystemUI: NowPlaying: Honor tap-to-expand setting for expanded overlay |
| `f71a7573e` | 2026-07-20 | SystemUI: NowPlaying: Add music lyrics mode [1/2] |
| `2f55009ec` | 2026-07-20 | SystemUI: DynamicBar: Hide nowplaying when keyguard panel visible |

The `[1/2]` markers mean matching `packages/apps/Settings` commits are needed
too, and the stack would then have to be reconciled with `axdynamicbar`, which
occupies the same lockscreen real estate. Not worth it for a MediaSession
re-skin.
