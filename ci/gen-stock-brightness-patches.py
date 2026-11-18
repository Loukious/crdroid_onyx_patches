#!/usr/bin/env python3
"""Generate brightness patches without changing real indexes.

Shared framework/device resource files and DisplayPowerController are filtered
at zero context, then re-diffed from temporary indexes with ordinary context.
The source/test files below are owned by this feature in the carried patch stack.
"""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
DISPLAY = "services/core/java/com/android/server/display/"
TESTS = "services/tests/displayservicetests/src/com/android/server/display/"
FEATURES = {
    "frameworks/base": (
        "0018-stock-onyx-auto-brightness.patch",
        [DISPLAY + name for name in (
            "AutomaticBrightnessController.java", "BrightnessMappingStrategy.java",
            "DisplayDeviceConfig.java", "OnyxBrightnessRampController.java",
            "OnyxBrightnessSensorPolicy.java", "OnyxLuxPolicy.java", "RampAnimator.java")]
        + [TESTS + name for name in (
            "BrightnessMappingStrategyTest.java", "DisplayDeviceConfigTest.java",
            "DisplayPowerControllerTest.java",
            "OnyxAutomaticBrightnessControllerTest.java",
            "OnyxBrightnessRampControllerTest.java", "OnyxBrightnessSensorPolicyTest.java",
            "OnyxBrightnessSensorSampleTimeTest.java",
            "OnyxLuxPolicyTest.java", "RampAnimatorTest.java")],
        {
            "config_enableOnyxAutoBrightness": ["core/res/res/values/config.xml",
                                                 "core/res/res/values/symbols.xml"],
            "Onyx|onyx|animateToWithCustomRate": [DISPLAY + "DisplayPowerController.java"],
        }),
    "device/xiaomi/onyx": (
        "0025-enable-stock-auto-brightness.patch", [],
        {"config_enableOnyxAutoBrightness": ["overlay/FrameworkOverlayOnyx/res/values/config.xml"]}),
    "vendor/xiaomi/onyx": (
        "0004-stock-brightness-display-config.patch",
        ["proprietary/vendor/etc/displayconfig/display_id_4630947173316895379.xml",
         "proprietary/vendor/etc/displayconfig/display_id_4630947258895476883.xml"], {}),
}

SYSTEM_UI_FEATURE = (
    "0019-fix-brightness-mode-tap-after-drag.patch",
    ["packages/SystemUI/" + path for path in (
        "src/com/android/systemui/brightness/ui/viewmodel/BrightnessSliderViewModel.kt",
        "src/com/android/systemui/brightness/ui/compose/BrightnessSlider.kt",
        "pods/brightness/src/main/data/repository/ScreenBrightnessDisplayManagerRepository.kt",
        "src/com/android/systemui/qs/composefragment/viewmodel/QSFragmentComposeViewModel.kt",
        "src/com/android/systemui/qs/composefragment/QSFragmentCompose.kt",
        "multivalentTests/src/com/android/systemui/brightness/ui/viewmodel/BrightnessSliderMirrorTouchTest.kt",
        "multivalentTests/src/com/android/systemui/brightness/ui/viewmodel/BrightnessSliderIntentOrderTest.kt",
        "pods/brightness/src/test/data/repository/ScreenBrightnessDisplayManagerRepositoryTest.kt",
    )],
    {},
)


def run(project, arguments, index, input_text=None):
    environment = {**os.environ, "GIT_INDEX_FILE": str(index)}
    result = subprocess.run(["git", "-C", str(project), *arguments],
                            env=environment, input=input_text,
                            capture_output=True, text=True, check=True)
    return result.stdout


def generate(rom, output):
    with tempfile.TemporaryDirectory(prefix="onyx-brightness-patches-") as temporary:
        features = [*FEATURES.items(), ("frameworks/base", SYSTEM_UI_FEATURE)]
        for number, (project_name, (name, whole, selected)) in enumerate(features):
            project = rom / project_name
            index = Path(temporary) / f"{number}-source-index"
            run(project, ["read-tree", "HEAD"], index)
            paths = [*whole, *(path for group in selected.values() for path in group)]
            # Only new feature files need intent-to-add, and it stays in the temporary index.
            for path in paths:
                tracked = run(project, ["ls-files", "--", path], index)
                if not tracked and (project / path).is_file():
                    run(project, ["add", "-N", "--", path], index)
            patch = run(project, ["diff", "--no-color", "--no-renames", "--binary",
                                   "HEAD", "--", *whole], index) if whole else ""
            for group, (pattern, group_paths) in enumerate(selected.items()):
                raw = run(project, ["diff", "--no-color", "--no-renames", "--binary",
                                    "-U0", "HEAD", "--", *group_paths], index)
                filtered = subprocess.run(
                    [sys.executable, str(HERE.parent / "hunk-filter.py"), "--keep", pattern],
                    input=raw, text=True, capture_output=True, check=True).stdout
                if not filtered:
                    raise RuntimeError(f"{project_name}: no stock brightness changes in {group_paths}")
                selected_index = Path(temporary) / f"{number}-{group}-selected-index"
                run(project, ["read-tree", "HEAD"], selected_index)
                run(project, ["apply", "--cached", "--unidiff-zero", "-"], selected_index, filtered)
                patch += run(project, ["diff", "--cached", "--no-color", "--no-renames",
                                       "--binary", "HEAD", "--", *group_paths], selected_index)
            if not patch:
                raise RuntimeError(f"{project_name}: generated patch is empty")
            target = output / "patches" / project_name.replace("/", "_") / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(patch)
            print(f"  {target.relative_to(output)}: {len(patch.splitlines())} lines")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("--out", type=Path, default=HERE.parent)
    args = parser.parse_args()
    generate(args.rom.resolve(), args.out.resolve())


if __name__ == "__main__":
    main()
