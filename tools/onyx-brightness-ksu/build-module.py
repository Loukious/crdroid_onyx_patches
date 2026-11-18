#!/usr/bin/env python3
"""Package the verified, exact-ROM brightness trial for KernelSU Next."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import zipfile


HERE = Path(__file__).resolve().parent
PANELS = ("display_id_4630947173316895379.xml", "display_id_4630947258895476883.xml")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest(entries):
    return "".join(f"{digest}  {name}\n" for name, digest in sorted(entries.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path, help="Originals, candidate and compatibility receipts")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--clearance", type=Path, required=True)
    parser.add_argument("--systemui", type=Path, help="Optional signed, verified exact-build SystemUI APK")
    parser.add_argument("--systemui-clearance", type=Path, help="Exact SystemUI compatibility clearance")
    parser.add_argument("--trial-number", type=int, choices=range(2, 10),
                        help="Trial revision; defaults to 3 with SystemUI, otherwise 2")
    args = parser.parse_args()
    work = args.work.resolve()
    clearance = json.loads(args.clearance.read_text())
    candidate = work / "candidate/services.jar"
    report = json.loads((work / "candidate/report.json").read_text())
    if clearance.get("passed") is not True or clearance.get("candidate_sha256") != sha(candidate):
        parser.error("Candidate must match a successful final device ABI/linkage clearance")
    if report["candidate_services_sha256"] != sha(candidate):
        parser.error("Candidate differs from its verified assembly receipt")
    original = work / "device-originals/services.jar"
    if sha(original) != report["original_services_sha256"]:
        parser.error("Original services.jar differs from the assembly baseline")
    if not report["untouched_classes_in_rewritten_dex_verified_by_full_canonical_smali"]:
        parser.error("Untouched installed class verification is required")
    if report["duplicate_class_definitions"]:
        parser.error("Duplicate class definitions are forbidden")
    panel_report = json.loads((work / "candidate/panel-validation.json").read_text())
    systemui_clearance = None
    if args.systemui:
        if not args.systemui_clearance:
            parser.error("SystemUI requires its exact compatibility clearance")
        systemui_clearance = json.loads(args.systemui_clearance.read_text())
        if (systemui_clearance.get("passed") is not True
                or systemui_clearance.get("candidate_apk_sha256") != sha(args.systemui)
                or systemui_clearance.get("original_apk_sha256")
                    != sha(work / "device-originals/SystemUIGoogle.apk")):
            parser.error("SystemUI payload or baseline differs from verified clearance")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="onyx-brightness-package-") as tmp:
        stage = Path(tmp)
        shutil.copytree(HERE / "module-template", stage, dirs_exist_ok=True)
        baseline, payload, archive = {}, {}, {}
        files = [("system/framework/services.jar", "/system/framework/services.jar", original, candidate)]
        files += [("vendor/etc/displayconfig/" + name, "/vendor/etc/displayconfig/" + name,
                   work / "device-originals" / name,
                   work / "candidate/panel-config" / name) for name in PANELS]
        if args.systemui:
            files.append(("system/system_ext/priv-app/SystemUIGoogle/SystemUIGoogle.apk",
                          "/system_ext/priv-app/SystemUIGoogle/SystemUIGoogle.apk",
                          work / "device-originals/SystemUIGoogle.apk", args.systemui))
        for relative, installed, before, after in files:
            if relative.endswith(".xml"):
                receipt = panel_report[after.name]
                if (receipt["baseline_sha256"] != sha(before)
                        or receipt["payload_sha256"] != sha(after)
                        or not receipt["original_mapping_hbm_and_other_config_unchanged"]):
                    parser.error("Panel configuration differs from its verified receipt")
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(after, target)
            baseline[installed] = sha(before)
            payload[installed] = sha(after)
            archive[relative] = sha(after)
        trial = args.trial_number or (3 if args.systemui else 2)
        (stage / "module.prop").write_text(
            "id=onyx_stock_brightness_test\n"
            "name=Onyx Stock Auto Brightness (KernelSU Test)\n"
            f"version=2026.11.14-trial.{trial}\nversionCode=202611140{trial}\nauthor=Loukious\n"
            "description=Stock dual-sensor policy and brightness ramps for Onyx Android 17 "
            "build 1794595788. Disable and reboot to restore.\n")
        (stage / "compatibility.prop").write_text(
            "ONYX_DEVICE=onyx\nONYX_INCREMENTAL=1794595788\nONYX_SDK=37\n")
        (stage / "baseline.sha256").write_text(manifest(baseline))
        (stage / "payload.sha256").write_text(manifest(payload))
        (stage / "archive-payload.sha256").write_text(manifest(archive))
        (stage / "README.md").write_text((HERE / "README.md").read_text())
        # KernelSU skips META-INF during extraction and deletes customize.sh/README.md.
        # Runtime manifests must describe the installed layout, not archive-only files.
        assets = {str(p.relative_to(stage)): sha(p) for p in stage.rglob("*")
                  if p.is_file() and str(p.relative_to(stage)) not in archive
                  and p.name not in ("customize.sh", "README.md", "assets.sha256")}
        (stage / "assets.sha256").write_text(manifest(assets))
        with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=9) as package:
            for p in sorted(stage.rglob("*")):
                if not p.is_file():
                    continue
                info = zipfile.ZipInfo(str(p.relative_to(stage)), (2026, 11, 14, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o100755 if p.suffix == ".sh" else 0o100644) << 16
                package.writestr(info, p.read_bytes(), compresslevel=9)
        receipt = {"zip_sha256": sha(args.output), "baseline": baseline, "payload": payload,
                   "candidate_clearance": clearance, "framework_apks_replaced": False,
                   "systemui_apk_replaced": bool(args.systemui), "systemui_clearance": systemui_clearance,
                   "rom_build": "1794595788", "rom_sdk": 37}
        args.output.with_suffix(".json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(args.output)
        print(receipt["zip_sha256"])


if __name__ == "__main__":
    main()
