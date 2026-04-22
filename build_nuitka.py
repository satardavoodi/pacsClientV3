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
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parent
THEME_QSS_SOURCE = PROJECT_ROOT / "generated-files" / "css" / "main.css"

# â”€â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def print_step(message: str) -> None:
    print("\n" + "=" * 80)
    print(f"  {message}")
    print("=" * 80 + "\n")


def load_spec(spec_path: Path) -> ModuleType:
    """Import the spec file as a Python module."""
    spec_obj = importlib.util.spec_from_file_location("nuitka_spec", str(spec_path))
    if spec_obj is None or spec_obj.loader is None:
        raise RuntimeError(f"Cannot load spec file: {spec_path}")
    mod = importlib.util.module_from_spec(spec_obj)
    spec_obj.loader.exec_module(mod)
    return mod


def check_nuitka() -> bool:
    """Verify that Nuitka is importable by the current interpreter."""
    print_step("Checking Nuitka installation")
    print(f"Using interpreter: {sys.executable}")
    try:
        r = subprocess.run(
            [sys.executable, "-m", "nuitka", "--version"],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            ver = r.stdout.strip().splitlines()[0]
            print(f"âœ… Nuitka version: {ver}")
            return True
    except Exception:
        pass
    print("â‌Œ Nuitka is NOT installed for this interpreter")
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


# â”€â”€â”€ Command builder â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def build_command(spec: ModuleType) -> list[str]:
    """Translate the spec module into a Nuitka CLI invocation."""
    cmd: list[str] = [sys.executable, "-m", "nuitka"]

    entry_point = getattr(spec, "ENTRY_POINT", "main.py")
    app_name    = getattr(spec, "APP_NAME", "AIPacs")
    output_dir  = getattr(spec, "OUTPUT_DIR", "dist/AIPacs_nuitka")
    standalone  = getattr(spec, "STANDALONE", True)
    onefile     = getattr(spec, "ONEFILE", False)
    win_console = getattr(spec, "WINDOWS_CONSOLE", False)
    icon        = getattr(spec, "ICON", "")
    plugins     = getattr(spec, "PLUGINS", [])
    nofollow    = getattr(spec, "NOFOLLOW_IMPORTS", [])
    forced      = getattr(spec, "FORCED_IMPORTS", [])
    include_pkg = getattr(spec, "INCLUDE_PACKAGES", [])
    data_dirs   = getattr(spec, "DATA_DIRS", [])
    opt_data    = getattr(spec, "OPTIONAL_DATA", [])
    jobs        = getattr(spec, "JOBS", 0)
    c_compiler  = getattr(spec, "C_COMPILER", None)
    show_prog   = getattr(spec, "SHOW_PROGRESS", True)
    show_mem    = getattr(spec, "SHOW_MEMORY", False)
    report      = getattr(spec, "REPORT_FILE", None)
    extra       = getattr(spec, "EXTRA_FLAGS", [])

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
            cmd.append("--windows-disable-console")
        if icon and (PROJECT_ROOT / icon).is_file():
            cmd.append(f"--windows-icon-from-ico={icon}")

    # Company / product info (optional, nice-to-have in exe properties)
    cmd.append(f"--product-name={app_name}")
    cmd.append(f"--product-version=2.3.7")
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
        cmd.append(f"--clang" if c_compiler == "clang" else f"--mingw64" if c_compiler == "mingw64" else f"--msvc=latest")

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
    parser.add_argument("--spec", default="AIPacs_nuitka.spec",
                        help="Path to the Nuitka spec file (default: AIPacs_nuitka.spec)")
    parser.add_argument("--clean", action="store_true",
                        help="Clean previous build artifacts before building")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the Nuitka command without executing it")
    args = parser.parse_args()

    print_step("AIPacs â€” Nuitka Build Process")

    # Load spec
    spec_path = Path(args.spec)
    if not spec_path.is_absolute():
        spec_path = PROJECT_ROOT / spec_path
    if not spec_path.is_file():
        print(f"â‌Œ Spec file not found: {spec_path}")
        return False

    print(f"  Spec file: {spec_path.name}")
    spec = load_spec(spec_path)

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

    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line, end="", flush=True)
    proc.wait()

    if proc.returncode != 0:
        print(f"\nâ‌Œ Nuitka exited with code {proc.returncode}")
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
