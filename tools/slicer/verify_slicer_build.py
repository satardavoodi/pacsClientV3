"""
Verify the integrity of an assembled Slicer runtime build.

Checks:
  - Critical files/directories exist
  - DLL counts are in expected ranges
  - intDir flattening was applied
  - Python packages are present
  - LauncherSettings.ini has expected sections

Usage:
    python tools/slicer/verify_slicer_build.py
    python tools/slicer/verify_slicer_build.py --build-dir "path/to/build"
"""
import argparse
import sys
from pathlib import Path


def _default_build_dir() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "modules" / "mpr" / "advanced_3d_slicer"
        / "slicer_custom_app" / "NewMPR2Slicer" / "build"
    )


def check(label: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    msg = f"  [{status}] {label}"
    if detail:
        msg += f"  ({detail})"
    print(msg)
    return ok


def verify(build_dir: Path) -> int:
    print(f"Verifying Slicer build at: {build_dir}\n")
    failures = 0

    # --- Critical files ---
    print("── Critical Files ──")
    critical = [
        ("Root launcher", "AIPacsAdvancedViewer.exe"),
        ("Launcher INI", "AIPacsAdvancedViewerLauncherSettings.ini"),
        ("Real exe", "bin/Release/AIPacsAdvancedViewer.exe"),
        ("Qt5Core", "deps/qt/Qt5Core.dll"),
        ("Qt5Widgets", "deps/qt/Qt5Widgets.dll"),
        ("Qt platform plugin", "deps/qt-plugins/platforms/qwindows.dll"),
        ("Python DLL", "python-install/bin/python312.dll"),
    ]
    for label, rel in critical:
        path = build_dir / rel
        if not check(label, path.exists(), str(rel)):
            failures += 1

    # --- Directory structure ---
    print("\n── Directory Structure ──")
    dirs = [
        ("bin/Release", "bin/Release"),
        ("lib modules", "lib/AIPacsAdvancedViewer-5.11/qt-loadable-modules"),
        ("deps/qt", "deps/qt"),
        ("deps/vtk", "deps/vtk"),
        ("deps/dcmtk", "deps/dcmtk"),
        ("python-install", "python-install/Lib/site-packages"),
        ("share", "share"),
    ]
    for label, rel in dirs:
        path = build_dir / rel
        if not check(label, path.is_dir(), str(rel)):
            failures += 1

    # --- DLL counts ---
    print("\n── DLL Counts ──")
    mod_dir = build_dir / "lib" / "AIPacsAdvancedViewer-5.11" / "qt-loadable-modules"
    if mod_dir.is_dir():
        root_dlls = list(mod_dir.glob("*.dll"))
        rel_dir = mod_dir / "Release"
        rel_dlls = list(rel_dir.glob("*.dll")) if rel_dir.is_dir() else []

        if not check("Loadable modules (root)", len(root_dlls) >= 40,
                      f"{len(root_dlls)} DLLs (expect ≥40)"):
            failures += 1

        if not check("Loadable modules (Release)", len(rel_dlls) >= 40,
                      f"{len(rel_dlls)} DLLs (expect ≥40)"):
            failures += 1

        # intDir flattening check
        if not check("intDir flattening applied",
                      len(root_dlls) >= len(rel_dlls),
                      f"root={len(root_dlls)} ≥ Release={len(rel_dlls)}"):
            failures += 1
    else:
        check("Loadable modules dir", False, "directory missing")
        failures += 1

    qt_dlls = list((build_dir / "deps" / "qt").glob("*.dll")) if (build_dir / "deps" / "qt").is_dir() else []
    if not check("Qt DLLs", len(qt_dlls) >= 15, f"{len(qt_dlls)} DLLs (expect ≥15)"):
        failures += 1

    vtk_dlls = list((build_dir / "deps" / "vtk").glob("*.dll")) if (build_dir / "deps" / "vtk").is_dir() else []
    if not check("VTK DLLs", len(vtk_dlls) >= 20, f"{len(vtk_dlls)} DLLs (expect ≥20)"):
        failures += 1

    # --- Python packages ---
    print("\n── Python Packages ──")
    sp = build_dir / "python-install" / "Lib" / "site-packages"
    required_pkgs = ["numpy", "scipy", "pydicom", "PIL", "requests", "dicomweb_client"]
    for pkg in required_pkgs:
        found = (sp / pkg).is_dir() if sp.is_dir() else False
        if not check(f"Package: {pkg}", found):
            failures += 1

    # --- LauncherSettings.ini ---
    print("\n── Launcher INI ──")
    ini_path = build_dir / "AIPacsAdvancedViewerLauncherSettings.ini"
    if ini_path.exists():
        content = ini_path.read_text(encoding="utf-8", errors="replace")
        for section in ["[Application]", "[LibraryPaths]", "[PYTHONPATH]",
                        "[EnvironmentVariables]", "[QT_PLUGIN_PATH]"]:
            if not check(f"INI section {section}", section in content):
                failures += 1

        if not check("INI references bin/Release",
                      "bin/Release/AIPacsAdvancedViewer.exe" in content):
            failures += 1
    else:
        check("Launcher INI exists", False)
        failures += 1

    # --- Total size ---
    print("\n── Size Summary ──")
    total = sum(f.stat().st_size for f in build_dir.rglob("*") if f.is_file())
    total_mb = total / 1048576
    check("Total size", total_mb > 500, f"{total_mb:.0f} MB (expect >500 MB)")

    # --- Result ---
    print(f"\n{'='*50}")
    if failures == 0:
        print("ALL CHECKS PASSED — build is ready for deployment.")
        return 0
    else:
        print(f"{failures} CHECK(S) FAILED — see above for details.")
        return 1


def main():
    parser = argparse.ArgumentParser(description="Verify Slicer runtime build integrity")
    parser.add_argument("--build-dir", type=Path, default=None,
                        help="Path to the build/ directory (default: auto-detect)")
    args = parser.parse_args()

    build_dir = args.build_dir or _default_build_dir()
    if not build_dir.exists():
        print(f"ERROR: Build directory not found: {build_dir}")
        print("Use --build-dir to specify the correct path, or run assemble_slicer_runtime.py first.")
        sys.exit(2)

    sys.exit(verify(build_dir))


if __name__ == "__main__":
    main()
