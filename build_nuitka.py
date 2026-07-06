"""
Nuitka build script for AIPacs
================================
Reads AIPacs_nuitka.spec (Python-based config) and drives Nuitka
with all the required flags, data dirs, plugins, and imports.

Usage:
    python build_nuitka.py                        # default spec
    python build_nuitka.py --spec my_custom.spec  # custom spec
    python build_nuitka.py --clean                # clean dist first
    python build_nuitka.py --dry-run              # show command only
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import datetime
from pathlib import Path
from types import ModuleType

# Fix encoding for Windows console
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)


PROJECT_ROOT = Path(__file__).resolve().parent
THEME_QSS_SOURCE = PROJECT_ROOT / "generated-files" / "css" / "main.css"

# â”€â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def print_step(message: str) -> None:
    print("\n" + "=" * 80)
    print(f"  {message}")
    print("=" * 80 + "\n")


def load_spec(spec_path: Path) -> ModuleType:
    """Import the spec file as a Python module.

    Uses SourceFileLoader explicitly so that any file extension works
    (including .spec files — importlib.spec_from_file_location only
    recognises .py/.pyc by default).
    """
    import importlib.machinery
    loader = importlib.machinery.SourceFileLoader("nuitka_spec", str(spec_path))
    spec_obj = importlib.util.spec_from_loader("nuitka_spec", loader, origin=str(spec_path))
    if spec_obj is None:
        raise RuntimeError(f"Cannot load spec file: {spec_path}")
    mod = importlib.util.module_from_spec(spec_obj)
    # __file__ must be set before exec_module so the spec can use Path(__file__)
    mod.__file__ = str(spec_path)
    loader.exec_module(mod)
    return mod


def check_nuitka() -> bool:
    """Verify that Nuitka is available for the current interpreter.

    Uses importlib.metadata for instant check (avoids spawning a subprocess
    which can take 30-90 s while Python compiles Nuitka's .pyc files on first use).
    """
    print_step("Checking Nuitka installation")
    print(f"Using interpreter: {sys.executable}")
    try:
        import importlib.metadata
        ver = importlib.metadata.version("nuitka")
        print(f"✅ Nuitka version: {ver}")
        return True
    except Exception:
        pass
    # Quick fallback: find_spec is instant
    if importlib.util.find_spec("nuitka") is not None:
        print(f"✅ Nuitka is installed (version unknown)")
        return True
    print(f"❌ Nuitka is NOT installed for this interpreter")
    return False

def install_nuitka() -> bool:
    """Pip-install Nuitka + ordered-set (recommended companion)."""
    print_step("Installing Nuitka")
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "nuitka", "ordered-set", "zstandard"]
    print(f"Running: {' '.join(cmd)}")
    r = subprocess.run(cmd)
    return r.returncode == 0


def verify_required_files(spec: ModuleType) -> bool:
    """Make sure entry point and mandatory data dirs exist."""
    print_step("Verifying required files")
    ok = True
    entry = PROJECT_ROOT / getattr(spec, "ENTRY_POINT", "main.py")
    if entry.is_file():
        print(f"âœ… Entry point: {entry.name}")
    else:
        print(f"â‌Œ Entry point missing: {entry}")
        ok = False

    for src, _ in getattr(spec, "DATA_DIRS", []):
        p = PROJECT_ROOT / src
        if p.exists():
            count = sum(1 for _ in p.rglob("*") if _.is_file()) if p.is_dir() else 1
            print(f"âœ… {src} ({count} file{'s' if count != 1 else ''})")
        else:
            print(f"â‌Œ {src} â€” NOT FOUND")
            ok = False

    icon = PROJECT_ROOT / getattr(spec, "ICON", "")
    if icon.is_file():
        print(f"âœ… Icon: {icon.name}")
    else:
        print(f"âڑ ï¸ڈ  Icon not found: {icon}  (build will continue without icon)")

    return ok


def clean(output_dir: Path) -> None:
    print_step("Cleaning previous Nuitka build artifacts")
    for d in [output_dir, PROJECT_ROOT / "build"]:
        if d.exists():
            print(f"Removing: {d}")
            shutil.rmtree(d, ignore_errors=True)

    # Remove __pycache__ dirs
    for root, dirs, _ in os.walk(PROJECT_ROOT):
        rp = Path(root)
        if "venv" in rp.parts or ".git" in rp.parts:
            continue
        for d in list(dirs):
            if d == "__pycache__":
                dp = rp / d
                print(f"Removing: {dp}")
                shutil.rmtree(dp, ignore_errors=True)
    print("âœ… Cleanup completed")


# â”€â”€â”€ Availability helpers (tolerate missing optional deps) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _toplevel_importable(name: str) -> bool:
    """True if the top-level package of `name` can be located in this venv.

    Mirrors the PyInstaller spec's try/except tolerance: an optional dependency
    that isn't installed (e.g. Custom_Widgets) must be SKIPPED, not turned into
    a fatal Nuitka '--include-package ... failed to locate' error.
    """
    top = name.split(".")[0]
    try:
        return importlib.util.find_spec(top) is not None
    except (ImportError, ValueError, ModuleNotFoundError, AttributeError):
        return False


def _module_importable(name: str) -> bool:
    """True if the FULL dotted module path can be located in this venv.

    Used for --include-module entries: Nuitka fatals on a module it cannot
    locate (e.g. legacy 'numpy.core._methods' on newer numpy where it moved to
    'numpy._core'), whereas PyInstaller only warns. Dropping the missing ones
    keeps the equivalent (new-name) entry that IS present.
    """
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, ModuleNotFoundError, AttributeError):
        return False
    except Exception:
        # find_spec can raise oddly for half-broken optional deps; treat as absent
        return False


def _distribution_available(dist: str) -> bool:
    try:
        import importlib.metadata as _md
        _md.distribution(dist)
        return True
    except Exception:
        return False


def _filter_available(items: list[str], *, kind: str, full_path: bool = False) -> list[str]:
    """Drop entries that can't be located. full_path=True checks the whole
    dotted module (for --include-module); otherwise just the top-level package
    (for --include-package / package-data)."""
    check = _module_importable if full_path else _toplevel_importable
    kept, skipped = [], []
    for item in items:
        if check(item):
            kept.append(item)
        else:
            skipped.append(item)
    if skipped:
        print(f"âš   Skipping {len(skipped)} unavailable {kind}: {', '.join(sorted(set(skipped)))}")
    return kept


# â”€â”€â”€ Command builder â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def build_command(spec: ModuleType) -> list[str]:
    """Translate the spec module into a Nuitka CLI invocation."""
    cmd: list[str] = [sys.executable, "-m", "nuitka"]

    entry_point = getattr(spec, "ENTRY_POINT", "main.py")
    app_name    = getattr(spec, "APP_NAME", "AIPacs")
    output_dir  = getattr(spec, "OUTPUT_DIR", "dist/AIPacs_nuitka")
    standalone  = getattr(spec, "STANDALONE", True)
    onefile     = getattr(spec, "ONEFILE", False)
    win_console = getattr(spec, "WINDOWS_CONSOLE", False)
    win_console_mode = os.environ.get("AIPACS_NUITKA_CONSOLE_MODE") or str(
        getattr(spec, "WINDOWS_CONSOLE_MODE", "attach") or "attach"
    )
    icon        = getattr(spec, "ICON", "")
    plugins     = getattr(spec, "PLUGINS", [])
    nofollow    = getattr(spec, "NOFOLLOW_IMPORTS", [])
    forced      = getattr(spec, "FORCED_IMPORTS", [])
    include_pkg = getattr(spec, "INCLUDE_PACKAGES", [])
    package_data = getattr(spec, "PACKAGE_DATA", [])
    dist_meta   = getattr(spec, "DIST_METADATA", [])
    data_dirs   = getattr(spec, "DATA_DIRS", [])
    opt_data    = getattr(spec, "OPTIONAL_DATA", [])
    jobs        = getattr(spec, "JOBS", 0)
    c_compiler  = getattr(spec, "C_COMPILER", None)
    show_prog   = getattr(spec, "SHOW_PROGRESS", True)
    show_mem    = getattr(spec, "SHOW_MEMORY", False)
    report      = getattr(spec, "REPORT_FILE", None)
    extra       = getattr(spec, "EXTRA_FLAGS", [])
    lto         = getattr(spec, "LTO", "auto")

    # Tolerate missing optional dependencies (like the PyInstaller spec does):
    # drop any include-package / include-module / package-data / metadata entry
    # whose top-level package (or distribution) isn't installed, instead of
    # letting Nuitka fatal-out on it.
    forced       = _filter_available(list(forced), kind="modules", full_path=True)
    include_pkg  = _filter_available(list(include_pkg), kind="packages")
    package_data = _filter_available(list(package_data), kind="package-data")
    dist_meta    = [d for d in dist_meta if _distribution_available(d)]

    # Mode
    if onefile:
        cmd.append("--onefile")
    elif standalone:
        cmd.append("--standalone")

    # Output
    cmd += [f"--output-dir={output_dir}"]
    cmd += [f"--output-filename={app_name}.exe"]

    # Windows specifics
    if sys.platform == "win32":
        if not win_console:
            cmd.append(f"--windows-console-mode={win_console_mode}")
        if icon and os.environ.get("AIPACS_NUITKA_ENABLE_EXE_ICON", "").strip().lower() in {"1", "true", "yes", "on"} and (PROJECT_ROOT / icon).is_file():
            cmd.append(f"--windows-icon-from-ico={icon}")

    # Company / product info (optional, nice-to-have in exe properties)
    cmd.append(f"--product-name={app_name}")
    # Load version from pyproject.toml (same source of truth as PyInstaller build)
    try:
        import tomllib
        with open(PROJECT_ROOT / "pyproject.toml", "rb") as _f:
            _ver = tomllib.load(_f).get("project", {}).get("version", "0.0.0")
    except Exception:
        _ver = "0.0.0"
    cmd.append(f"--product-version={_ver}")
    cmd.append(f"--company-name=AIPacs")
    cmd.append(f"--file-description={app_name} - Professional Medical Imaging Suite")

    # Plugins
    for p in plugins:
        cmd.append(f"--enable-plugin={p}")

    # NoFollow imports (anti-bloat)
    for m in nofollow:
        cmd.append(f"--nofollow-import-to={m}")

    # Forced / hidden imports
    for m in forced:
        cmd.append(f"--include-module={m}")

    # Whole-package includes
    for pkg in include_pkg:
        cmd.append(f"--include-package={pkg}")

    # Force include PySide6 package data
    cmd.append("--include-package-data=PySide6")

    # Extra package data (qtawesome fonts, Custom_Widgets themes, ...)
    for pkg in package_data:
        cmd.append(f"--include-package-data={pkg}")

    # Distribution metadata — REQUIRED for pylibjpeg codec plugin discovery.
    # Without this, compressed DICOM (JPEG 2000 / JPEG-lossless / RLE) silently
    # fails to decode in the frozen build. This is the Nuitka equivalent of the
    # PyInstaller spec's copy_metadata() calls.
    for dist in dist_meta:
        cmd.append(f"--include-distribution-metadata={dist}")

    # Data directories
    for src, dst in data_dirs:
        p = PROJECT_ROOT / src
        if p.is_dir():
            cmd.append(f"--include-data-dir={src}={dst}")
        elif p.is_file():
            cmd.append(f"--include-data-files={src}={dst}/")

    for src, dst in opt_data:
        p = PROJECT_ROOT / src
        if p.is_dir():
            cmd.append(f"--include-data-dir={src}={dst}")
        elif p.is_file():
            if dst == ".":
                cmd.append(f"--include-data-files={src}={os.path.basename(src)}")
            else:
                cmd.append(f"--include-data-files={src}={dst}/{os.path.basename(src)}")

    # qtawesome fonts (critical for icons)
    try:
        import qtawesome
        qa_dir = Path(qtawesome.__file__).parent / "fonts"
        if qa_dir.is_dir():
            cmd.append(f"--include-data-dir={qa_dir}=qtawesome/fonts")
            print(f"âœ… Including qtawesome fonts from: {qa_dir}")
    except Exception:
        print("âڑ ï¸ڈ  qtawesome not found â€“ icons may be missing at runtime")

    # Parallelism
    if jobs:
        cmd.append(f"--jobs={jobs}")

    # Compiler
    if c_compiler:
        if c_compiler == "clang":
            cmd.append("--clang")
        elif c_compiler == "mingw64":
            cmd.append("--mingw64")
        elif c_compiler == "zig":
            cmd.append("--zig")
        else:
            cmd.append("--msvc=latest")

    # Progress
    if show_prog:
        cmd.append("--show-progress")
    if show_mem:
        cmd.append("--show-memory")

    # Report
    if report:
        cmd.append(f"--report={report}")

    # Extra verbatim flags
    cmd.extend(extra)

    # LTO
    if lto in ("yes", "no", "auto"):
        cmd.append(f"--lto={lto}")

    # Anti-bloat (requires Nuitka >= 1.0)
    # cmd.append("--anti-bloat")

    # Finally the entry point
    cmd.append(entry_point)

    return cmd


# â”€â”€â”€ Post-build â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def resolve_dist_dir(spec: ModuleType) -> Path:
    """Work out where Nuitka actually placed output."""
    output_dir = Path(getattr(spec, "OUTPUT_DIR", "dist/AIPacs_nuitka"))
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir

    entry = getattr(spec, "ENTRY_POINT", "main.py")
    entry_stem = Path(entry).stem   # "main"

    # Nuitka standalone puts results in  <output_dir>/<stem>.dist/
    dist_candidate = output_dir / f"{entry_stem}.dist"
    if dist_candidate.is_dir():
        return dist_candidate

    # Sometimes the output is directly in output_dir
    return output_dir


def stage_resources(dist_dir: Path) -> None:
    """Copy Qss / Fonts next to the executable (same as PyInstaller build)."""
    print("\nStaging extra resources next to executable ...")
    for name in ["Qss", "Fonts"]:
        src = PROJECT_ROOT / name
        dst = dist_dir / name
        if src.exists() and not dst.exists():
            shutil.copytree(src, dst, dirs_exist_ok=True)
            print(f"âœ… Staged: {name} â†’ {dst}")
        elif dst.exists():
            print(f"âœ… {name} already present in dist")


    if THEME_QSS_SOURCE.exists():
        qss_dir = dist_dir / "Qss"
        qss_dir.mkdir(parents=True, exist_ok=True)
        dest = qss_dir / "main.qss"
        shutil.copy2(THEME_QSS_SOURCE, dest)
        print(f"أ¢إ“â€¦ Theme stylesheet synced: {dest}")
    else:
        print(f"أ¢ع‘آ أ¯آ¸عˆ  Theme stylesheet missing: {THEME_QSS_SOURCE}")


def rename_exe(dist_dir: Path, spec: ModuleType) -> Path | None:
    """Rename main.exe â†’ AIPacs.exe if needed."""
    app_name = getattr(spec, "APP_NAME", "AIPacs")
    entry_stem = Path(getattr(spec, "ENTRY_POINT", "main.py")).stem

    expected = dist_dir / f"{app_name}.exe"
    if expected.is_file():
        return expected

    alt = dist_dir / f"{entry_stem}.exe"
    if alt.is_file():
        alt.rename(expected)
        print(f"âœ… Renamed {alt.name} â†’ {expected.name}")
        return expected

    # search any exe
    for f in dist_dir.glob("*.exe"):
        f.rename(expected)
        print(f"âœ… Renamed {f.name} â†’ {expected.name}")
        return expected

    return None


def verify_build(dist_dir: Path, spec: ModuleType) -> bool:
    print_step("Verifying Nuitka build output")
    exe = rename_exe(dist_dir, spec)
    if exe is None:
        print("â‌Œ No executable found in dist directory!")
        return False

    size_mb = exe.stat().st_size / (1024 * 1024)
    print(f"âœ… Executable: {exe}")
    print(f"   Size: {size_mb:.2f} MB")

    required = ["PacsClient", "Fonts", "Qss"]
    ok = True
    for d in required:
        if (dist_dir / d).exists():
            print(f"âœ… {d}")
        else:
            print(f"â‌Œ {d} â€” MISSING")
            ok = False

    return ok


def create_build_info(dist_dir: Path) -> None:
    info_path = dist_dir / "BUILD_INFO.txt"
    content = f"""AIPacs Build Information (Nuitka)
==================================

Build Date:        {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Builder:           Nuitka
Python Executable: {sys.executable}
Python Version:    {sys.version}
Platform:          {sys.platform}

Output Directory:  {dist_dir}
"""
    try:
        info_path.write_text(content, encoding="utf-8")
        print(f"âœ… Build info: {info_path}")
    except Exception as e:
        print(f"âڑ ï¸ڈ  Could not write build info: {e}")


# â”€â”€â”€ Main â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def main() -> bool:
    parser = argparse.ArgumentParser(description="Build AIPacs with Nuitka")
    parser.add_argument("--spec", default=None,
                        help="Path to the Nuitka spec file "
                             "(default: builder nuitka/AIPacs_nuitka.spec.py)")
    parser.add_argument("--clean", action="store_true",
                        help="Clean previous build artifacts before building")
    parser.add_argument("--onefile", action="store_true",
                        help="Build a single-file executable (overrides spec)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the Nuitka command without executing it")
    args = parser.parse_args()

    print_step("AIPacs â€” Nuitka Build Process")

    # Load spec. Default lives inside the nuitka builder folder. Fall back to a
    # legacy root-level spec name if someone kept one there.
    if args.spec:
        spec_path = Path(args.spec)
    else:
        spec_path = PROJECT_ROOT / "builder nuitka" / "AIPacs_nuitka.spec.py"
        if not spec_path.is_file():
            spec_path = PROJECT_ROOT / "AIPacs_nuitka.spec"
    if not spec_path.is_absolute():
        spec_path = PROJECT_ROOT / spec_path
    if not spec_path.is_file():
        print(f"â‌Œ Spec file not found: {spec_path}")
        return False

    print(f"  Spec file: {spec_path.name}")
    spec = load_spec(spec_path)

    # CLI override: force single-file mode regardless of spec setting.
    if args.onefile:
        spec.ONEFILE = True
        print("  Mode override: --onefile requested")

    # Verify prerequisites
    if not verify_required_files(spec):
        print("\nâ‌Œ Aborted â€” required files missing")
        return False

    if not check_nuitka():
        print("Attempting to install Nuitka ...")
        if not install_nuitka():
            print("â‌Œ Could not install Nuitka")
            return False
        if not check_nuitka():
            print("â‌Œ Nuitka still not working after install")
            return False

    output_dir = Path(getattr(spec, "OUTPUT_DIR", "dist/AIPacs_nuitka"))
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir

    if args.clean:
        clean(output_dir)

    # Build
    cmd = build_command(spec)

    print_step("Nuitka command")
    # Pretty-print the command
    print("  " + " \\\n    ".join(cmd[:5]))
    if len(cmd) > 5:
        print("    " + " \\\n    ".join(cmd[5:]))
    print()

    if args.dry_run:
        print("(dry-run mode â€” not executing)")
        return True

    print_step("Building AIPacs with Nuitka")
    print("This may take a while (10-30 minutes on first build) ...\n")

    # Build environment: pin BLAS thread counts for a stable compile (the
    # equivalent of the old PyInstaller numpy runtime hook), plus any RUNTIME_ENV
    # declared in the spec.
    env = os.environ.copy()
    for _k, _v in getattr(spec, "RUNTIME_ENV", {}).items():
        env.setdefault(_k, _v)

    # Tee all Nuitka output to a timestamped log so build failures are
    # inspectable after the fact.
    log_dir = PROJECT_ROOT / "builder nuitka" / "output" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"nuitka_build_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
    print(f"  Build log: {log_path}\n")

    returncode = 1
    with open(log_path, "w", encoding="utf-8", errors="replace") as log_file:
        log_file.write("COMMAND: " + " ".join(cmd) + "\n\n")
        log_file.flush()
        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="", flush=True)
            log_file.write(line)
        proc.wait()
        returncode = proc.returncode

    if returncode != 0:
        print(f"\nâ‌Œ Nuitka exited with code {returncode}")
        print(f"   See full build log: {log_path}")
        return False

    print("\nâœ… Nuitka compilation finished")

    # Post-build
    dist_dir = resolve_dist_dir(spec)
    stage_resources(dist_dir)

    ok = verify_build(dist_dir, spec)
    create_build_info(dist_dir)

    print_step("Build Process Complete!")
    exe_name = getattr(spec, "APP_NAME", "AIPacs") + ".exe"
    print(f"âœ… AIPacs has been built with Nuitka!")
    print(f"\nًں“پ Output: {dist_dir}")
    print(f"ًںڑ€ Run: {dist_dir / exe_name}")
    return ok


if __name__ == "__main__":
    try:
        sys.exit(0 if main() else 1)
    except KeyboardInterrupt:
        print("\n\nâڑ ï¸ڈ  Build interrupted by user")
        sys.exit(1)
