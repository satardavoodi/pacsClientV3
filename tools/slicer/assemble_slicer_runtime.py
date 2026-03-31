"""
Assemble a self-contained Slicer runtime from the build tree at C:\\S\\NB.

This copies ONLY the runtime files (DLLs, Python, modules) needed to run
AIPacsAdvancedViewer, producing a portable directory that doesn't depend
on any system-installed components.

Run once:  python tools/slicer/assemble_slicer_runtime.py
"""
import shutil
import sys
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
SUPERBUILD   = Path(r"C:\S\NB")
SLICER_BUILD = SUPERBUILD / "Slicer-build"
QT_DIR       = Path(r"C:\Qt\5.15.2\msvc2019_64")

TARGET = (
    Path(__file__).resolve().parents[2]
    / "modules" / "mpr" / "advanced_3d_slicer"
    / "slicer_custom_app" / "NewMPR2Slicer" / "build"
)

# ── Qt modules actually needed by Slicer ──────────────────────────────────
QT_MODULES = [
    "Core", "Gui", "Widgets", "Network", "OpenGL",
    "Multimedia", "MultimediaWidgets", "PrintSupport", "Svg", "Xml",
    "Sql", "Qml", "QmlModels", "Quick", "QuickWidgets",
    "WebChannel", "WebEngine", "WebEngineCore", "WebEngineWidgets",
    "Positioning", "Concurrent",
]

# Subset of Qt plugins Slicer actually uses
QT_PLUGIN_DIRS = [
    "platforms",        # qwindows.dll — essential
    "imageformats",     # JPEG, PNG, SVG, etc.
    "iconengines",      # SVG icon engine
    "styles",           # Windows Vista style
    "sqldrivers",       # SQLite driver (for Slicer settings)
]


def copy_tree(src: Path, dst: Path, *, only_ext: set | None = None):
    """Recursively copy *src* → *dst*, optionally filtering by extension."""
    if not src.exists():
        print(f"  [SKIP] Source missing: {src}")
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.rglob("*"):
        if item.is_dir():
            continue
        if only_ext and item.suffix.lower() not in only_ext:
            continue
        rel = item.relative_to(src)
        dest_file = dst / rel
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dest_file)


def copy_files(src: Path, dst: Path, *, glob: str = "*"):
    """Copy files (non-recursive) matching *glob* from *src* → *dst*."""
    if not src.exists():
        print(f"  [SKIP] Source missing: {src}")
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.glob(glob):
        if item.is_file():
            shutil.copy2(item, dst / item.name)


def _flatten_release_subdirs(lib_dir: Path):
    """Copy files from Release/ subdirectories up to their parent.

    Slicer's module factory concatenates searchPath + intDir to find
    C++ modules.  In a SuperBuild, intDir is "Release" so it looks in
    e.g. qt-loadable-modules/Release/.  In our assembled build intDir
    is empty, so the factory looks in qt-loadable-modules/ directly.
    By copying files from Release/ into the parent we satisfy both cases.
    """
    for subdir in ["qt-loadable-modules", "cli-modules", "ITKFactories"]:
        release = lib_dir / subdir / "Release"
        if not release.is_dir():
            continue
        parent = release.parent
        count = 0
        for item in release.iterdir():
            if item.is_file():
                shutil.copy2(item, parent / item.name)
                count += 1
        if count:
            print(f"  ✓ Flattened {subdir}/Release/: {count} files → {subdir}/")


def main():
    # Verify source directories
    for p, label in [
        (SLICER_BUILD, "Slicer-build"),
        (SUPERBUILD / "python-install", "python-install"),
        (QT_DIR, "Qt 5.15.2"),
    ]:
        if not p.exists():
            print(f"FATAL: {label} not found at {p}")
            sys.exit(1)

    # Clean previous assembly (keep AIPACS_LAUNCH_ERROR.txt for reference)
    if TARGET.exists():
        print(f"Removing previous assembly at {TARGET} …")
        shutil.rmtree(TARGET, ignore_errors=True)
    TARGET.mkdir(parents=True, exist_ok=True)

    total_bytes = 0

    def report(label: str, path: Path):
        nonlocal total_bytes
        size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        total_bytes += size
        print(f"  ✓ {label}: {size / 1048576:.1f} MB")

    # ── 1. Root launcher exe ──────────────────────────────────────────────
    print("\n[1/11] Root launcher exe")
    src_launcher = SLICER_BUILD / "AIPacsAdvancedViewer.exe"
    shutil.copy2(src_launcher, TARGET / "AIPacsAdvancedViewer.exe")
    total_bytes += src_launcher.stat().st_size
    print(f"  ✓ Launcher: {src_launcher.stat().st_size / 1048576:.1f} MB")

    # ── 2. bin/ directory ─────────────────────────────────────────────────
    print("\n[2/11] bin/ (Release + Python + plugins)")
    copy_tree(SLICER_BUILD / "bin" / "Release", TARGET / "bin" / "Release")
    copy_tree(SLICER_BUILD / "bin" / "Python",  TARGET / "bin" / "Python")
    copy_tree(SLICER_BUILD / "bin" / "iconengines", TARGET / "bin" / "iconengines")
    copy_tree(SLICER_BUILD / "bin" / "styles",  TARGET / "bin" / "styles")
    report("bin", TARGET / "bin")

    # ── 3. lib/ directory ─────────────────────────────────────────────────
    print("\n[3/11] lib/AIPacsAdvancedViewer-5.11/")
    copy_tree(
        SLICER_BUILD / "lib" / "AIPacsAdvancedViewer-5.11",
        TARGET / "lib" / "AIPacsAdvancedViewer-5.11",
        only_ext={".dll", ".pyd", ".py", ".pem", ".crt", ".json", ".txt",
                  ".so", ".ini", ".cfg", ".yaml", ".xml", ".ui"},
    )
    # Flatten Release/ subdirs so the module factory finds DLLs even when
    # intDir is empty (our assembled build doesn't set intDir=Release).
    _flatten_release_subdirs(TARGET / "lib" / "AIPacsAdvancedViewer-5.11")
    report("lib", TARGET / "lib")

    # ── 4. share/ directory ───────────────────────────────────────────────
    print("\n[4/11] share/")
    copy_tree(SLICER_BUILD / "share", TARGET / "share")
    report("share", TARGET / "share")

    # ── 5. python-install/ ────────────────────────────────────────────────
    print("\n[5/11] python-install/ (Python 3.12)")
    copy_tree(SUPERBUILD / "python-install", TARGET / "python-install")
    report("python-install", TARGET / "python-install")

    # ── 6-10. External dependencies ──────────────────────────────────────
    deps = [
        ("openssl",   SUPERBUILD / "OpenSSL-install" / "Release" / "bin"),
        ("tbb",       SUPERBUILD / "tbb-install" / "redist" / "intel64" / "vc14"),
        ("vtk",       SUPERBUILD / "VTK-build" / "bin" / "Release"),
        ("teem",      SUPERBUILD / "teem-build" / "bin" / "Release"),
        ("dcmtk",     SUPERBUILD / "DCMTK-build" / "bin" / "Release"),
        ("itk",       SUPERBUILD / "ITK-build" / "bin" / "Release"),
        ("ctk",       SUPERBUILD / "CTK-build" / "CTK-build" / "bin" / "Release"),
        ("pythonqt",  SUPERBUILD / "CTK-build" / "PythonQt-build" / "Release"),
        ("libarchive",SUPERBUILD / "LibArchive-install" / "bin"),
        ("sem",       SUPERBUILD / "SlicerExecutionModel-build"
                      / "ModuleDescriptionParser" / "bin" / "Release"),
        ("jsoncpp",   SUPERBUILD / "JsonCpp-build" / "bin" / "Release"),
    ]
    print("\n[6/11] External deps (DLLs)")
    for name, src in deps:
        copy_files(src, TARGET / "deps" / name, glob="*.dll")
        copy_files(src, TARGET / "deps" / name, glob="*.exe")
        copy_files(src, TARGET / "deps" / name, glob="*.pyd")
    # CTK Python bindings
    copy_tree(
        SUPERBUILD / "CTK-build" / "CTK-build" / "bin" / "Python",
        TARGET / "deps" / "ctk-python",
    )
    # CTK designer plugins (register ctk* widgets as Qt plugins)
    ctk_designer_src = SUPERBUILD / "CTK-build" / "CTK-build" / "bin" / "designer"
    ctk_designer_dst = TARGET / "deps" / "ctk" / "designer"
    for sub in [ctk_designer_src, ctk_designer_src / "Release"]:
        copy_files(sub, ctk_designer_dst, glob="*.dll")
    report("deps", TARGET / "deps")

    # ── VTK site-packages (Python bindings for VTK) ──────────────────────
    print("\n[7/11] VTK Python site-packages")
    copy_tree(
        SUPERBUILD / "VTK-build" / "lib" / "site-packages",
        TARGET / "deps" / "vtk-site-packages",
    )
    report("deps (updated)", TARGET / "deps")

    # ── 8. Qt DLLs ──────────────────────────────────────────────────────
    print("\n[8/11] Qt5 DLLs")
    qt_dst = TARGET / "deps" / "qt"
    qt_dst.mkdir(parents=True, exist_ok=True)
    for mod in QT_MODULES:
        dll = QT_DIR / "bin" / f"Qt5{mod}.dll"
        if dll.exists():
            shutil.copy2(dll, qt_dst / dll.name)
    # Extra Qt dependencies
    for extra in ["d3dcompiler_47.dll", "libEGL.dll", "libGLESv2.dll",
                  "opengl32sw.dll", "QtWebEngineProcess.exe"]:
        src = QT_DIR / "bin" / extra
        if src.exists():
            shutil.copy2(src, qt_dst / extra)
    report("Qt DLLs", qt_dst)

    # ── 9. Qt plugins ────────────────────────────────────────────────────
    print("\n[9/11] Qt5 plugins")
    for plugin_dir in QT_PLUGIN_DIRS:
        src = QT_DIR / "plugins" / plugin_dir
        if src.exists():
            copy_tree(src, TARGET / "deps" / "qt-plugins" / plugin_dir)
    report("Qt plugins", TARGET / "deps" / "qt-plugins")

    # ── 10. SplashScreen ─────────────────────────────────────────────────
    print("\n[10/11] Splash screen + branding")
    splash_src = (
        Path(__file__).resolve().parents[2]
        / "modules" / "mpr" / "advanced_3d_slicer"
        / "slicer_custom_app" / "NewMPR2Slicer"
        / "Applications" / "NewMPR2SlicerApp" / "Resources" / "Images"
    )
    for img in splash_src.glob("*"):
        if img.is_file():
            shutil.copy2(img, TARGET / img.name)

    # ── 11. Launcher settings ini ────────────────────────────────────────
    print("\n[11/11] Creating LauncherSettings.ini")
    write_launcher_ini(TARGET / "AIPacsAdvancedViewerLauncherSettings.ini")
    print("  ✓ LauncherSettings.ini written")

    # ── Summary ──────────────────────────────────────────────────────────
    final_bytes = sum(
        f.stat().st_size for f in TARGET.rglob("*") if f.is_file()
    )
    print(f"\n{'='*60}")
    print(f"Assembly complete: {TARGET}")
    print(f"Total size: {final_bytes / 1048576:.0f} MB "
          f"({final_bytes / 1073741824:.2f} GB)")
    print(f"{'='*60}")


def write_launcher_ini(path: Path):
    """Write AIPacsAdvancedViewerLauncherSettings.ini with all-relative paths."""
    # <APPLAUNCHER_DIR> = directory of the launcher exe = build/
    # <APPLAUNCHER_SETTINGS_DIR> = directory of the ini = build/
    # Both are the same since exe and ini sit at build root.
    ini = r"""[General]
launcherNoSplashScreen=true
additionalLauncherHelpShortArgument=-h
additionalLauncherHelpLongArgument=--help
additionalLauncherNoSplashArguments=--no-splash,--help,--version,--home,--program-path,--no-main-window,--settings-path,--temporary-path

[Application]
path=<APPLAUNCHER_DIR>/bin/Release/AIPacsAdvancedViewer.exe
arguments=
name=AIPacsAdvancedViewer
revision=34362
organizationDomain=kitware.com
organizationName=Kitware, Inc.

[ExtraApplicationToLaunch]

cmd/shortArgument=
cmd/help=Start cmd
cmd/path=C:/Windows/System32/cmd.exe
cmd/arguments=/c start cmd

[Environment]
additionalPathVariables=QT_PLUGIN_PATH,PYTHONPATH,LibraryPaths

[LibraryPaths]
1\path=<APPLAUNCHER_DIR>/bin/Release
2\path=<APPLAUNCHER_DIR>/deps/qt
3\path=../lib/AIPacsAdvancedViewer-5.11/qt-loadable-modules
4\path=../lib/AIPacsAdvancedViewer-5.11/qt-loadable-modules/Release
5\path=<APPLAUNCHER_DIR>/lib/AIPacsAdvancedViewer-5.11/cli-modules/Release
6\path=<APPLAUNCHER_DIR>/lib/AIPacsAdvancedViewer-5.11/qt-loadable-modules/Release
7\path=<APPLAUNCHER_DIR>/deps/openssl
8\path=<APPLAUNCHER_DIR>/python-install/bin
9\path=<APPLAUNCHER_DIR>/deps/tbb
10\path=<APPLAUNCHER_DIR>/deps/vtk
11\path=<APPLAUNCHER_DIR>/deps/teem
12\path=<APPLAUNCHER_DIR>/deps/dcmtk
13\path=<APPLAUNCHER_DIR>/deps/itk
14\path=<APPLAUNCHER_DIR>/deps/ctk
15\path=<APPLAUNCHER_DIR>/deps/pythonqt
16\path=<APPLAUNCHER_DIR>/deps/libarchive
17\path=<APPLAUNCHER_DIR>/deps/sem
18\path=<APPLAUNCHER_DIR>/python-install/Lib/site-packages/numpy/core
19\path=<APPLAUNCHER_DIR>/python-install/Lib/site-packages/numpy/lib
20\path=<APPLAUNCHER_DIR>/deps/jsoncpp
size=20

[Paths]
1\path=<APPLAUNCHER_DIR>/bin/Release
2\path=<APPLAUNCHER_DIR>/deps/qt
3\path=<APPLAUNCHER_DIR>/lib/AIPacsAdvancedViewer-5.11/cli-modules/Release
4\path=<APPLAUNCHER_DIR>/python-install/bin
5\path=<APPLAUNCHER_DIR>/python-install/Scripts
6\path=<APPLAUNCHER_DIR>/deps/teem
size=6

[EnvironmentVariables]
SLICER_HOME=<APPLAUNCHER_DIR>
ITK_AUTOLOAD_PATH=<APPLAUNCHER_DIR>/lib/AIPacsAdvancedViewer-5.11/ITKFactories/Release
PIP_REQUIRE_VIRTUALENV=0
SSL_CERT_FILE=<APPLAUNCHER_DIR>/share/AIPacsAdvancedViewer-5.11/Slicer.crt
PYTHONHOME=<APPLAUNCHER_DIR>/python-install
PYTHONNOUSERSITE=1
PIP_DISABLE_PIP_VERSION_CHECK=1

[QT_PLUGIN_PATH]
1\path=<APPLAUNCHER_DIR>/bin
2\path=<APPLAUNCHER_DIR>/deps/ctk
3\path=<APPLAUNCHER_DIR>/deps/qt-plugins
size=3

[PYTHONPATH]
1\path=<APPLAUNCHER_DIR>/bin/Release
2\path=<APPLAUNCHER_DIR>/bin/Python
3\path=<APPLAUNCHER_DIR>/lib/AIPacsAdvancedViewer-5.11/qt-loadable-modules/Release
4\path=<APPLAUNCHER_DIR>/lib/AIPacsAdvancedViewer-5.11/qt-loadable-modules/Python
5\path=<APPLAUNCHER_DIR>/lib/AIPacsAdvancedViewer-5.11/qt-scripted-modules
6\path=<APPLAUNCHER_DIR>/python-install/Lib
7\path=<APPLAUNCHER_DIR>/python-install/Lib/lib-dynload
8\path=<APPLAUNCHER_DIR>/python-install/Lib/site-packages
9\path=<APPLAUNCHER_DIR>/deps/vtk-site-packages
10\path=<APPLAUNCHER_DIR>/deps/ctk-python
11\path=<APPLAUNCHER_DIR>/deps/ctk
size=11
"""
    path.write_text(ini.strip(), encoding="utf-8")


if __name__ == "__main__":
    main()
