"""
Enhanced build script for AIPacs (fixed):
- Always runs PyInstaller using the CURRENT interpreter (venv-safe)
- Verifies resources in both dist root and _internal (PyInstaller 6 behavior)
- Optionally stages Qss/Fonts/config next to the EXE for runtime path simplicity
"""
from __future__ import annotations

import os
import sys
import shutil
import subprocess
from pathlib import Path

# Fix encoding for Windows console
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parent


def print_step(message: str) -> None:
    print("\n" + "=" * 80)
    print(f"  {message}")
    print("=" * 80 + "\n")


def run_command(args: list[str], description: str, cwd: Path | None = None, env: dict | None = None) -> bool:
    """Run a command with real-time output."""
    print(f"Running: {description}")
    print(f"Command: {' '.join(map(str, args))}\n")
    print("-" * 80)

    proc = subprocess.Popen(
        args,
        cwd=str(cwd) if cwd else None,
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

    proc.wait()
    print("-" * 80)

    if proc.returncode != 0:
        print(f"❌ Error: {description} failed with exit code {proc.returncode}")
        return False

    print(f"✅ Success: {description} completed")
    return True


def clean_build_directories() -> None:
    print_step("Cleaning previous build artifacts")

    for dir_name in ["build", "dist"]:
        p = PROJECT_ROOT / dir_name
        if p.exists():
            print(f"Removing directory: {p}")
            shutil.rmtree(p, ignore_errors=True)

    # Clean __pycache__ directories
    for root, dirs, files in os.walk(PROJECT_ROOT):
        root_p = Path(root)
        if "venv" in root_p.parts or ".git" in root_p.parts:
            continue
        for d in list(dirs):
            if d == "__pycache__":
                dp = root_p / d
                print(f"Removing: {dp}")
                shutil.rmtree(dp, ignore_errors=True)

    print("✅ Cleanup completed")


def verify_required_files() -> bool:
    print_step("Verifying required files and directories")

    entry_point = None
    if (PROJECT_ROOT / "AIPacs.py").is_file():
        entry_point = "AIPacs.py"
    elif (PROJECT_ROOT / "main.py").is_file():
        entry_point = "main.py"

    if not entry_point:
        print("❌ No entry point found (AIPacs.py or main.py)")
        return False
    print(f"✅ Found entry point: {entry_point}")

    spec_file = None
    if (PROJECT_ROOT / "AIPacs.spec").is_file():
        spec_file = "AIPacs.spec"
    elif (PROJECT_ROOT / "main.spec").is_file():
        spec_file = "main.spec"

    if spec_file:
        print(f"✅ Found spec file: {spec_file}")
    else:
        print("❌ Spec file not found (AIPacs.spec or main.spec)")
        return False

    required_dirs = ["PacsClient", "Fonts", "Qss"]
    required_files = ["requirements.txt"]

    ok = True
    for d in required_dirs:
        p = PROJECT_ROOT / d
        if p.is_dir():
            file_count = sum(1 for _ in p.rglob("*") if _.is_file())
            print(f"✅ Directory: {d} ({file_count} files)")
        else:
            print(f"❌ Directory: {d}")
            ok = False

    for f in required_files:
        p = PROJECT_ROOT / f
        if p.is_file():
            print(f"✅ File: {f}")
        else:
            print(f"❌ File: {f}")
            ok = False

    if ok:
        print("\n✅ All required files and directories exist")
    else:
        print("\n❌ Some required files or directories are missing")
    return ok


def check_pyinstaller() -> bool:
    print_step("Checking PyInstaller (venv-safe)")

    print(f"Using interpreter: {sys.executable}")
    try:
        r = subprocess.run([sys.executable, "-m", "PyInstaller", "--version"], capture_output=True, text=True)
        if r.returncode == 0:
            print(f"✅ PyInstaller is installed (for this interpreter): {r.stdout.strip()}")
            return True
    except Exception:
        pass

    print("❌ PyInstaller not found for this interpreter")
    return False


def install_pyinstaller() -> bool:
    print_step("Installing PyInstaller into this interpreter/venv")
    return run_command([sys.executable, "-m", "pip", "install", "--upgrade", "pip", "pyinstaller"], "PyInstaller installation", cwd=PROJECT_ROOT)


def build_application() -> bool:
    print_step("Building AIPacs application")

    spec_file = None
    if (PROJECT_ROOT / "AIPacs.spec").exists():
        spec_file = "AIPacs.spec"
    elif (PROJECT_ROOT / "main.spec").exists():
        spec_file = "main.spec"

    if not spec_file:
        print("❌ Spec file not found (AIPacs.spec or main.spec)")
        return False

    print(f"Using spec file: {spec_file}")

    env = os.environ.copy()
    # Prevent PyInstaller/matplotlib from falling back to TkAgg when Qt is present
    # (especially important for Qt apps)
    env.setdefault("MPLBACKEND", "QtAgg")

    cmd = [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", spec_file]
    return run_command(cmd, "Application build", cwd=PROJECT_ROOT, env=env)


def _copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst, dirs_exist_ok=True)


def stage_resources_next_to_exe(dist_dir: Path) -> None:
    """
    Ensure these folders exist next to AIPacs.exe.
    This avoids runtime path headaches if your app loads e.g. 'Qss/...' relative to exe.
    """
    print("\nStaging resources next to EXE (Qss, Fonts, config) ...")
    for name in ["Qss", "Fonts"]:
        src = PROJECT_ROOT / name
        dst = dist_dir / name
        if src.exists():
            _copy_tree(src, dst)
            print(f"✅ Staged: {name} -> {dst}")


def verify_build() -> bool:
    print_step("Verifying build output")

    dist_dir = PROJECT_ROOT / "dist" / "AIPacs"
    exe_path = dist_dir / "AIPacs.exe"

    if not exe_path.exists():
        print(f"❌ Build failed: Executable not found at {exe_path}")
        return False

    size_mb = exe_path.stat().st_size / (1024 * 1024)
    print("✅ Build successful!")
    print(f"   Executable: {exe_path}")
    print(f"   Size: {size_mb:.2f} MB")

    required_dirs = ["PacsClient", "Fonts", "Qss"]
    internal = dist_dir / "_internal"

    print("\nVerifying bundled resources (root OR _internal):")
    all_present = True
    for d in required_dirs:
        root_p = dist_dir / d
        internal_p = internal / d
        if root_p.exists():
            print(f"✅ {d} (root)")
        elif internal_p.exists():
            print(f"✅ {d} (_internal)")
        else:
            print(f"❌ {d} (MISSING)")
            all_present = False

    print("\nContents of dist/AIPacs/:")
    try:
        items = sorted([p.name for p in dist_dir.iterdir()])
        for item in items[:30]:
            p = dist_dir / item
            print(f"   {'📁' if p.is_dir() else '📄'} {item}{'/' if p.is_dir() else ''}")
        if len(items) > 30:
            print(f"   ... and {len(items) - 30} more items")
    except Exception as e:
        print(f"   Error listing directory: {e}")

    # Stage runtime resources next to exe (recommended if your app uses relative paths)
    stage_resources_next_to_exe(dist_dir)

    # Re-check after staging
    print("\nRe-check resources after staging:")
    staged_ok = True
    for d in ["Fonts", "Qss"]:
        if not (dist_dir / d).exists():
            print(f"❌ {d} still missing next to exe")
            staged_ok = False
        else:
            print(f"✅ {d} exists next to exe")

    return all_present and staged_ok


def create_build_info() -> None:
    print_step("Creating build information file")
    import datetime

    dist_dir = PROJECT_ROOT / "dist" / "AIPacs"
    info_path = dist_dir / "BUILD_INFO.txt"

    content = f"""AIPacs Build Information
========================

Build Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Python Executable: {sys.executable}
Python Version: {sys.version}
Platform: {sys.platform}

Output Directory: {dist_dir}
Executable: {dist_dir / "AIPacs.exe"}
"""
    try:
        info_path.write_text(content, encoding="utf-8")
        print(f"✅ Build information created: {info_path}")
    except Exception as e:
        print(f"⚠️  Could not create build info: {e}")


def main() -> bool:
    print_step("AIPacs Application Build Process")
    print("This script will build a complete, standalone version of AIPacs")

    if not verify_required_files():
        print("\n❌ Build aborted: Required files missing")
        return False

    if not check_pyinstaller():
        if not install_pyinstaller():
            print("\n❌ Build aborted: Could not install PyInstaller")
            return False

    clean_build_directories()

    if not build_application():
        print("\n❌ Build failed")
        return False

    ok = verify_build()
    if not ok:
        print("\n⚠️  Build completed but some resources may be missing")
        print("    (Note: PyInstaller 6 may place datas under _internal)")

    create_build_info()

    print_step("Build Process Complete!")
    out = PROJECT_ROOT / "dist" / "AIPacs"
    print("✅ AIPacs has been successfully built!")
    print(f"\n📁 Output location: {out}")
    print("🚀 Run 'dist/AIPacs/AIPacs.exe' to start the application")
    return True


if __name__ == "__main__":
    try:
        sys.exit(0 if main() else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Build process interrupted by user")
        sys.exit(1)
