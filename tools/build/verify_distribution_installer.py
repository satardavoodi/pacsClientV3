"""Compile-check Inno scripts with synthetic files and /O-; never produce or run an installer."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def main():
    from builder.build_release import find_iscc, INSTALLER_SCRIPT, INSTALLER_SCRIPT_WOA
    compiler = find_iscc()
    if compiler is None:
        raise RuntimeError("Inno Setup is required for this compile-only probe")
    results = []
    with tempfile.TemporaryDirectory(prefix="aipacs-synthetic-installer-") as temporary:
        stage = Path(temporary)
        for name in ("core/AIPacs.exe", "plugin_packages/advanced_mpr/payload/AIPacsAdvancedViewer.exe",
                     "plugin_packages/advanced_mpr/payload/offline_lumbar/python/python.exe"):
            file = stage / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b"synthetic fixture - never executable")
        (stage / "plugin_packages/advanced_mpr/payload/offline_lumbar/manifest.json").write_text("{}")
        (stage / "plugin_packages/module_package_feed.json").write_text('{"packages":[]}')
        for edition, include_offline, script in (
            ("standard", 0, INSTALLER_SCRIPT),
            ("arm", 0, INSTALLER_SCRIPT_WOA),
            ("eagle-eye", 1, INSTALLER_SCRIPT),
        ):
            command = [str(compiler), "/O-", "/Q", "/DMyAppVersion=9.9.9",
                       f"/DStageDir={stage}", f"/DInstallerOutputDir={stage}",
                       f"/DDistributionEdition={edition}", "/DIncludeAdvancedMpr=1",
                       f"/DIncludeOfflineLumbar={include_offline}", str(script)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=60)
            if result.returncode:
                raise RuntimeError(edition + " compile-only check failed:\n" + result.stdout + result.stderr)
            results.append({"edition": edition, "compile_only_passed": True})
        (stage / "plugin_packages/advanced_mpr/payload/offline_lumbar/manifest.json").unlink()
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        if result.returncode == 0 or "Eagle Eye requires" not in result.stdout + result.stderr:
            raise RuntimeError("Eagle Eye did not fail closed for a missing model manifest")
    print(json.dumps({"synthetic_only": True, "installer_output_enabled": False,
                      "outputs": results, "missing_model_rejected": True}))


if __name__ == "__main__":
    main()
