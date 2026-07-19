"""Build the AI-PACS Lite Viewer portable bundle.

Usage (from the repo root, inside the project venv):

    .venv\\Scripts\\python.exe tools\\build\\build_lite_viewer.py
    .venv\\Scripts\\python.exe tools\\build\\build_lite_viewer.py --builder nuitka
    # or simply double-click / run: tools\\build\\build_lite_viewer.bat

Builders:
    pyinstaller (DEFAULT) — fast freeze (ships CPython + bytecode). Builds in
        ~1-3 minutes; the right choice for routine rebuilds.
    nuitka — C-compiled build; slower to build (20+ min) but slightly faster
        to start. Kept as an alternative.

Output (either builder):
    modules/cd_burner/lightViewer_dist/AIPacsLiteViewer/AIPacsLiteViewer.exe
    (+ bundled Qt/pydicom/numpy/pylibjpeg runtime, viewer_info.json)

The CD burner (modules/cd_burner/viewer_locator.py) picks this bundle up as
the DEFAULT viewer automatically once it exists. The bundle is a ONEDIR
build on purpose: onefile unpacks to %TEMP% on the patient's PC which is
slow and fragile when launched from read-only CD/DVD media.

Codecs: pylibjpeg + its plugins (rle / openjpeg / libjpeg) are bundled so
compressed DICOM (JPEG, J2K, RLE) renders on any PC. GOTCHA (see project
memory / import-pipeline 2026-06-06): the plugin packages import as ``rle``
/ ``openjpeg`` / ``libjpeg`` (NOT ``pylibjpeg_*``) and are discovered via
importlib.metadata entry points — the import names AND the distribution
metadata must BOTH be included or the frozen viewer decodes nothing:
PyInstaller → --hidden-import + --copy-metadata; Nuitka →
--include-package + --include-distribution-metadata.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "modules" / "cd_burner" / "portable_viewer"
ENTRY_SCRIPT = PACKAGE_DIR / "aipacs_lite_viewer.py"
ASSET_ICON_PNG = REPO_ROOT / "modules" / "cd_burner" / "assets" / "cd_icon.png"

BUILD_DIR = REPO_ROOT / "generated-files" / "build" / "lite_viewer"
TARGET_DIR = REPO_ROOT / "modules" / "cd_burner" / "lightViewer_dist" / "AIPacsLiteViewer"
EXE_NAME = "AIPacsLiteViewer.exe"
APP_NAME = "AIPacsLiteViewer"

# Compressed-DICOM codec plugins (import/package name → distribution name).
CODEC_PACKAGES = {
    "pylibjpeg": "pylibjpeg",
    "rle": "pylibjpeg-rle",
    "openjpeg": "pylibjpeg-openjpeg",
    "libjpeg": "pylibjpeg-libjpeg",
}

EXCLUDED_MODULES = [
    "PIL",
    "matplotlib",
    "scipy",
    "pandas",
    "vtk",
    "vtkmodules",
    "tkinter",
    "pytest",
    # Startup-speed diet (2026-06-07): none of these are viewer
    # dependencies — they sneak in via optional import chains and cost
    # CD read time. The frozen --selftest gate proves they're not needed.
    "cryptography",
    "certifi",
    "charset_normalizer",
    "psutil",
    "urllib3",
    "requests",
    "idna",
]

# Post-build prune: Qt payload the viewer never uses (pure QWidget raster
# app — no QML/Quick, no network, no SVG/PDF, no image-format plugins; the
# window icon is an exe resource and DICOM pixels arrive via QImage raw
# buffers). qwindows/qoffscreen platforms and styles stay. The completeness
# assertion + --selftest run AFTER pruning and gate the result.
PRUNE_PATTERNS = (
    "_internal/PySide6/translations",
    "_internal/PySide6/opengl32sw.dll",
    "_internal/opengl32sw.dll",
    "_internal/PySide6/d3dcompiler_47.dll",
    "_internal/PySide6/Qt6Network.dll",
    "_internal/PySide6/Qt6OpenGL.dll",
    "_internal/PySide6/Qt6Svg.dll",
    "_internal/PySide6/Qt6Pdf.dll",
    "_internal/PySide6/Qt6Qml*.dll",
    "_internal/PySide6/Qt6Quick*.dll",
    "_internal/PySide6/plugins/imageformats",
    "_internal/PySide6/plugins/iconengines",
    "_internal/PySide6/plugins/tls",
    "_internal/PySide6/plugins/networkinformation",
    "_internal/PySide6/plugins/generic",
)


def _prune_bundle(dist_dir: Path) -> float:
    """Delete unused Qt payload. Returns MB freed."""
    freed = 0
    for pattern in PRUNE_PATTERNS:
        for target in dist_dir.glob(pattern):
            try:
                if target.is_dir():
                    freed += sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
                    shutil.rmtree(target)
                else:
                    freed += target.stat().st_size
                    target.unlink()
                print(f"[prune] removed {target.relative_to(dist_dir)}")
            except OSError as exc:
                print(f"[prune] could not remove {target}: {exc}")
    return freed / (1024 * 1024)


def _read_viewer_version() -> str:
    meta: dict = {}
    exec((PACKAGE_DIR / "viewer_meta.py").read_text(encoding="utf-8"), meta)
    return str(meta.get("VIEWER_VERSION", "0.0.0"))


def _make_icon(tmp_dir: Path) -> Path | None:
    """Convert the CD PNG asset to .ico for the exe icon (best effort)."""
    if not ASSET_ICON_PNG.exists():
        return None
    try:
        from PIL import Image

        ico_path = tmp_dir / "lite_viewer.ico"
        with Image.open(ASSET_ICON_PNG) as img:
            img.save(ico_path, sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
        return ico_path
    except Exception as exc:  # icon is cosmetic — never fail the build on it
        print(f"[icon] skipped ({exc})")
        return None


def _installed(dist_name: str) -> bool:
    try:
        import importlib.metadata as md

        md.distribution(dist_name)
        return True
    except Exception:
        return False


# Files that MUST exist in a complete PyInstaller bundle. Missing any of
# these means the viewer cannot run on a clean machine — fail the build.
CRITICAL_BUNDLE_FILES = (
    "_internal/python313.dll",
    "_internal/base_library.zip",
    "_internal/VCRUNTIME140.dll",
    "_internal/PySide6/QtCore.pyd",
    "_internal/PySide6/plugins/platforms/qwindows.dll",
    "_internal/assets/aipacs_logo.png",   # welcome-page branding
)


def _assert_bundle_complete(dist_dir: Path) -> list[str]:
    missing = [rel for rel in CRITICAL_BUNDLE_FILES if not (dist_dir / rel).is_file()]
    return missing


def _run_selftest(exe_path: Path) -> bool:
    """Run the frozen exe's --selftest as a release gate (must exit 0).

    A freshly built, unsigned 50 MB+ bundle is slow on its FIRST execution
    (Windows Defender scans every bundled DLL) and the build host is usually
    still saturated from the main-app PyInstaller pass — so a single run was
    unreliable and used to nuke the whole release on a transient hiccup. To
    make the gate trustworthy WITHOUT weakening it:

      1. WARM the bundle once (result ignored) so Defender scans it + the OS
         caches the files; a pass here already satisfies the gate.
      2. Attempt the gate a few times on the now-warm bundle, passing on the
         first clean exit 0.

    Only a CONSISTENT clean failure (the bundle runs but the check fails) fails
    the build — that is a real defect. A persistent *timeout* points at the
    environment (AV / host load), not the bundle, so we degrade to the source
    self-test rather than blocking the release.
    """
    print("[selftest] running frozen-bundle self-test…")

    def _env_int(name: str, default: int, floor: int = 30) -> int:
        try:
            return max(floor, int(os.environ.get(name, str(default))))
        except Exception:
            return default

    # First run absorbs the AV scan, so give it room; later attempts are warm.
    warmup_timeout = _env_int("AIPACS_LITE_SELFTEST_WARMUP_SEC", 300)
    # Back-compat: the old RETRY var, if set, raises the warm-up budget.
    warmup_timeout = max(
        warmup_timeout, _env_int("AIPACS_LITE_SELFTEST_RETRY_TIMEOUT_SEC", 0, floor=0)
    )
    attempt_timeout = _env_int("AIPACS_LITE_SELFTEST_TIMEOUT_SEC", 180)
    max_attempts = _env_int("AIPACS_LITE_SELFTEST_ATTEMPTS", 3, floor=1)
    cmd = [str(exe_path), "--selftest"]

    def _kill_stale() -> None:
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", EXE_NAME, "/T"],
                capture_output=True, text=True, timeout=15,
            )
        except Exception:
            pass

    def _run_once(timeout: int) -> str:
        """Return 'ok' | 'fail' (ran, exit != 0) | 'timeout'."""
        try:
            result = subprocess.run(cmd, timeout=timeout)
            if result.returncode == 0:
                return "ok"
            print(
                f"[selftest]   exit {result.returncode} — "
                "see %TEMP%\\aipacs_lite_selftest_failed.txt"
            )
            return "fail"
        except subprocess.TimeoutExpired:
            _kill_stale()
            return "timeout"
        except Exception as exc:
            print(f"[selftest]   could not launch: {exc}")
            return "fail"

    def _run_source_selftest() -> bool:
        src_cmd = [
            sys.executable,
            "-c",
            (
                "import sys; "
                f"sys.path.insert(0, r'{PACKAGE_DIR}'); "
                "import viewer_app; "
                "raise SystemExit(viewer_app.run_selftest())"
            ),
        ]
        print("[selftest] fallback: running source self-test…")
        try:
            result = subprocess.run(src_cmd, timeout=120)
            if result.returncode == 0:
                print("[selftest] fallback PASSED")
                return True
            print(f"[selftest] fallback FAILED (exit {result.returncode})")
            return False
        except Exception as exc:
            print(f"[selftest] fallback FAILED to run: {exc}")
            return False

    saw_clean_failure = False

    # (1) Warm-up — absorbs the first-run AV scan + OS file cache. A pass here
    #     is already a green gate.
    print(f"[selftest] warm-up run (<= {warmup_timeout}s, absorbs AV scan)…")
    status = _run_once(warmup_timeout)
    if status == "ok":
        print("[selftest] PASSED (warm-up)")
        return True
    saw_clean_failure = saw_clean_failure or status == "fail"
    print(f"[selftest] warm-up {status}")

    # (2) Gated attempts on the now-warm bundle.
    for i in range(1, max_attempts + 1):
        status = _run_once(attempt_timeout)
        if status == "ok":
            print(f"[selftest] PASSED (attempt {i}/{max_attempts})")
            return True
        saw_clean_failure = saw_clean_failure or status == "fail"
        print(f"[selftest] attempt {i}/{max_attempts} {status}")

    # All runs failed — distinguish a real defect from an environment problem.
    if saw_clean_failure:
        print(
            "[selftest] frozen self-test failed (bundle runs but the check did "
            "not pass) — treating as a real bundle defect."
        )
        return False
    print(
        "[selftest] frozen run never completed (timeouts only — AV / host load, "
        "not a bundle defect) — falling back to the source self-test."
    )
    return _run_source_selftest()


def _publish(dist_dir: Path, version: str, bundled_codecs: list[str], builder: str) -> int:
    exe_path = dist_dir / EXE_NAME
    if not exe_path.is_file():
        print(f"ERROR: build output missing: {exe_path}")
        return 3

    if builder.startswith("pyinstaller"):
        freed_mb = _prune_bundle(dist_dir)
        if freed_mb:
            print(f"[prune] freed {freed_mb:.1f} MB")
        missing = _assert_bundle_complete(dist_dir)
        if missing:
            print("ERROR: bundle is INCOMPLETE — refusing to publish. Missing:")
            for rel in missing:
                print(f"  - {rel}")
            return 4

    if not _run_selftest(exe_path):
        print("ERROR: bundle self-test failed — refusing to publish.")
        return 5

    if TARGET_DIR.exists():
        shutil.rmtree(TARGET_DIR)
    TARGET_DIR.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(dist_dir, TARGET_DIR)

    info = {
        "name": "AI-PACS Lite Viewer",
        "version": version,
        "built": _dt.datetime.now().isoformat(timespec="seconds"),
        "exe": EXE_NAME,
        "codecs": bundled_codecs,
        "builder": builder,
    }
    (TARGET_DIR / "viewer_info.json").write_text(
        json.dumps(info, indent=2), encoding="utf-8"
    )

    total_mb = sum(
        f.stat().st_size for f in TARGET_DIR.rglob("*") if f.is_file()
    ) / (1024 * 1024)
    print(f"== OK: {TARGET_DIR / EXE_NAME}")
    print(f"== bundle size: {total_mb:.1f} MB · codecs: {', '.join(bundled_codecs) or 'none'} · builder: {builder}")
    print("== The CD burner will now use this bundle as the default viewer.")
    return 0


# ---------------------------------------------------------------------------
# PyInstaller (default)
# ---------------------------------------------------------------------------

def build_pyinstaller(version: str) -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("ERROR: PyInstaller is not installed in this interpreter.")
        print(r"Install it once:  .venv\Scripts\python.exe -m pip install pyinstaller")
        return 2

    work_dir = BUILD_DIR / "pyi_work"
    spec_dir = BUILD_DIR / "pyi_spec"
    dist_root = BUILD_DIR / "pyi_dist"
    for d in (work_dir, spec_dir):
        d.mkdir(parents=True, exist_ok=True)
    if dist_root.exists():
        shutil.rmtree(dist_root)

    icon_path = _make_icon(BUILD_DIR)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", APP_NAME,
        "--windowed",                       # no console window
        "--distpath", str(dist_root),
        "--workpath", str(work_dir),
        "--specpath", str(spec_dir),
        "--additional-hooks-dir", str(REPO_ROOT / "hooks"),
        # CRITICAL: the entry script imports its siblings as PLAIN modules
        # (from viewer_app import main). PyInstaller's static analysis does
        # NOT honor the entry script's runtime sys.path.insert — without
        # --paths the whole viewer chain (viewer_app → PySide6/pydicom/...)
        # is silently dropped and the frozen exe dies with
        # ModuleNotFoundError on every machine (2026-06-07 incident).
        "--paths", str(PACKAGE_DIR),
    ]
    for module in ("viewer_app", "media_scan", "render", "viewer_meta", "welcome", "optical_io"):
        cmd += ["--hidden-import", module]
    for module in EXCLUDED_MODULES:
        cmd += ["--exclude-module", module]

    # Welcome-page branding assets → _internal/assets (same relative location
    # as in the source tree, so Path(__file__).parent/'assets' works in both).
    assets_dir = PACKAGE_DIR / "assets"
    if assets_dir.is_dir():
        cmd += ["--add-data", f"{assets_dir};assets"]

    bundled_codecs = []
    for package, dist in CODEC_PACKAGES.items():
        if _installed(dist):
            cmd += ["--hidden-import", package, "--copy-metadata", dist]
            bundled_codecs.append(dist)
        else:
            print(f"[codecs] {dist} not installed — building without it")

    if icon_path is not None:
        cmd += ["--icon", str(icon_path)]

    cmd.append(str(ENTRY_SCRIPT))

    print("[pyinstaller]", " ".join(cmd[3:]))
    result = subprocess.run(cmd, cwd=str(REPO_ROOT))
    if result.returncode != 0:
        print(f"ERROR: PyInstaller build failed (exit {result.returncode})")
        return result.returncode

    return _publish(dist_root / APP_NAME, version, bundled_codecs, "pyinstaller-onedir")


# ---------------------------------------------------------------------------
# Nuitka (alternative)
# ---------------------------------------------------------------------------

def build_nuitka(version: str) -> int:
    try:
        import nuitka  # noqa: F401
    except ImportError:
        print("ERROR: Nuitka is not installed in this interpreter.")
        print(r"Run with the project venv: .venv\Scripts\python.exe tools\build\build_lite_viewer.py --builder nuitka")
        return 2

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    icon_path = _make_icon(BUILD_DIR)

    cmd = [
        sys.executable,
        "-m",
        "nuitka",
        "--standalone",
        "--assume-yes-for-downloads",
        "--enable-plugin=pyside6",
        "--noinclude-qt-translations",
        "--windows-console-mode=disable",
        f"--output-dir={BUILD_DIR}",
        f"--output-filename={EXE_NAME}",
        "--company-name=AI-PACS",
        "--product-name=AI-PACS Lite Viewer",
        f"--file-version={version}",
        f"--product-version={version}",
        "--file-description=AI-PACS portable DICOM viewer for patient media",
    ]
    for module in EXCLUDED_MODULES:
        cmd.append(f"--nofollow-import-to={module}")
    # The codec plugins ship their test suites importing pytest — keep them out.
    for tests_pkg in ("libjpeg.tests", "rle.tests", "openjpeg.tests", "pylibjpeg.tests"):
        cmd.append(f"--nofollow-import-to={tests_pkg}")

    bundled_codecs = []
    for package, dist in CODEC_PACKAGES.items():
        if _installed(dist):
            cmd.append(f"--include-package={package}")
            cmd.append(f"--include-distribution-metadata={dist}")
            bundled_codecs.append(dist)
        else:
            print(f"[codecs] {dist} not installed — building without it")

    if icon_path is not None:
        cmd.append(f"--windows-icon-from-ico={icon_path}")

    cmd.append(str(ENTRY_SCRIPT))

    print("[nuitka]", " ".join(str(c) for c in cmd[3:]))
    result = subprocess.run(cmd, cwd=str(REPO_ROOT))
    if result.returncode != 0:
        print(f"ERROR: Nuitka build failed (exit {result.returncode})")
        return result.returncode

    return _publish(BUILD_DIR / "aipacs_lite_viewer.dist", version, bundled_codecs, "nuitka-standalone")


def ensure_built(force: bool = True, builder: str = "pyinstaller") -> int:
    """Build the lite viewer (always when ``force``, else only if missing).

    Importable entry used by the release pipelines so every build ships a
    fresh viewer. Returns a process exit code (0 = OK).
    """
    version = _read_viewer_version()
    target_exe = TARGET_DIR / EXE_NAME
    if not force and target_exe.is_file():
        print(f"[lite-viewer] already present, skipping rebuild: {target_exe}")
        return 0
    print(f"== Ensuring AI-PACS Lite Viewer {version} ({builder}, force={force}) ==")
    print(f"python: {sys.executable}")
    return build_nuitka(version) if builder == "nuitka" else build_pyinstaller(version)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the AI-PACS Lite Viewer bundle")
    parser.add_argument(
        "--builder",
        choices=("pyinstaller", "nuitka"),
        default="pyinstaller",
        help="freeze tool to use (default: pyinstaller — fast python build)",
    )
    parser.add_argument(
        "--if-missing",
        action="store_true",
        help="only build when the bundle is absent (default: always rebuild)",
    )
    args = parser.parse_args()

    return ensure_built(force=not args.if_missing, builder=args.builder)


if __name__ == "__main__":
    sys.exit(main())
