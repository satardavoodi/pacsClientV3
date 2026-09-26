"""Keep the shipped Slicer startup path aligned with Developer Run."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil


STARTUP_SOURCE = Path("modules/mpr/advanced_3d_slicer/slicer_custom_app/startup_script.py")
STARTUP_RUNTIME = Path("bin/Python/startup_script.py")
PRESENTATION_COMPANIONS = (
    STARTUP_SOURCE.parent / "presentation.py",
    STARTUP_SOURCE.parent / "unified_logging.py",
    Path("Qss/numeric_controls.py"),
)
DEVELOPER_RUNTIME = Path(
    "modules/mpr/advanced_3d_slicer/slicer_custom_app/NewMPR2Slicer/build"
)
NATIVE_SOURCE_ROOT = DEVELOPER_RUNTIME.parent
NATIVE_EXECUTABLE = Path("bin/Release/AIPacsAdvancedViewer.exe")
NATIVE_PROVENANCE = Path("aipacs-native-build.json")
APP_LOCAL_VC_RUNTIME_HASHES = {
    "concrt140.dll": "2405355f0a58067b258f8df33c327e3a3d716eaac5a3a5aebb757842d85bd376",
    "msvcp140_1.dll": "bfad5aef4c63a669e3c140655cdfdf395b6c979b400a447bd5dcb65ed8826c3d",
    "msvcp140_2.dll": "3ea06f0ee098b4823cb79599df3780e7f23cce52c19aac31d2a0d47efe33a5e9",
    "msvcp140_atomic_wait.dll": "640b2aefced484d0368eea5bdd06addd0658a3a70a49256e560d6923b404a479",
    "msvcp140_codecvt_ids.dll": "f2069a52880ec885ee7f0511186100eb7fada0411a2b4948fafea7735b878a18",
    "msvcp140.dll": "0f885b509a685d2bbfa652fed26b5fb31d88fbdab0a978c641d1c7b8aa460aa9",
    "vccorlib140.dll": "19839407c3fdbc824e5bce189bf68ddf8097f12ec28b757797ffa0415c144ddd",
    "vcruntime140_1.dll": "1f2d41c4aa5db0bc33ebf7b66d72943a817d7ce6cbe880502a9403823633093f",
    "vcruntime140_threads.dll": "219915cf20822f34d5e7c1fdd4e21ae7f3396881096c51036225fb8f84b47afa",
    "vcruntime140.dll": "d5e4d9a3e835fa679450145d6a7d94e36573a509317111904d9b3712c30d9066",
}
NATIVE_SOURCE_SUFFIXES = {".cxx", ".h", ".cmake", ".qrc", ".qss", ".ui", ".png", ".svg", ".ico", ".icns", ".bmp", ".ini", ".rc"}
RUNTIME_ITEMS = (
    "AIPacsAdvancedViewer.exe", "AIPacsAdvancedViewerLauncherSettings.ini",
    "bin", "deps", "lib", "python-install", "share",
    "Logo.png", "LogoFull.png", "SplashScreen.png", str(NATIVE_PROVENANCE),
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def native_source_files(project_root: Path) -> list[Path]:
    return _native_source_files(project_root / NATIVE_SOURCE_ROOT)


def _native_source_files(source_root: Path) -> list[Path]:
    if not source_root.is_dir():
        raise FileNotFoundError(f"Native Slicer source is missing: {source_root}")
    files = []
    for directory, subdirectories, names in os.walk(source_root):
        subdirectories[:] = [name for name in subdirectories if name not in {"build", ".git", "__pycache__"}]
        for name in names:
            path = Path(directory) / name
            if name == "CMakeLists.txt" or path.suffix.lower() in NATIVE_SOURCE_SUFFIXES:
                files.append(path)
    if not files:
        raise FileNotFoundError(f"Native Slicer source files are missing: {source_root}")
    return sorted(files, key=lambda path: path.relative_to(source_root).as_posix())


def native_source_sha256(project_root: Path) -> str:
    return _native_source_sha256(project_root / NATIVE_SOURCE_ROOT)


def _native_source_sha256(source_root: Path) -> str:
    digest = hashlib.sha256()
    for path in _native_source_files(source_root):
        digest.update(path.relative_to(source_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(file_sha256(path)))
    return digest.hexdigest()


def assert_compiler_source_matches_project(project_root: Path, superbuild: Path) -> None:
    """Reject a native build made from a stale short-path copy of the app source."""
    cache = superbuild / "CMakeCache.txt"
    if not cache.is_file():
        raise FileNotFoundError(f"Custom Slicer CMake cache is missing: {cache}")
    prefix = "CMAKE_HOME_DIRECTORY:INTERNAL="
    home = next((line[len(prefix):].strip() for line in cache.read_text(encoding="utf-8").splitlines()
                 if line.startswith(prefix)), "")
    if not home:
        raise ValueError("Custom Slicer CMake cache has no compiler source location")
    compiler_source = Path(home).resolve()
    if not (compiler_source / "CMakeLists.txt").is_file():
        raise FileNotFoundError(f"Custom Slicer compiler source is missing: {compiler_source}")
    if _native_source_sha256(compiler_source) != native_source_sha256(project_root):
        raise ValueError("Custom Slicer compiler source differs from current repository native source")


def assert_native_binary_fresh(project_root: Path, executable: Path) -> None:
    """Do not attest an assembled runtime from a build older than native source."""
    if not executable.is_file():
        raise FileNotFoundError(f"Native Slicer executable is missing: {executable}")
    newest_source = max(native_source_files(project_root), key=lambda path: path.stat().st_mtime_ns)
    if executable.stat().st_mtime_ns < newest_source.stat().st_mtime_ns:
        raise ValueError(f"Native Slicer binary predates current source: {newest_source}")


def write_native_build_provenance(project_root: Path, runtime: Path) -> None:
    """Record a freshly compiled native viewer, never an old assembly copy."""
    executable = runtime / NATIVE_EXECUTABLE
    assert_native_binary_fresh(project_root, executable)
    provenance = {"format_version": 1, "native_source_sha256": native_source_sha256(project_root),
                  "native_executable_sha256": file_sha256(executable)}
    (runtime / NATIVE_PROVENANCE).write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")


def verify_native_build_provenance(project_root: Path, runtime: Path) -> None:
    """Fail closed when native C++/resources changed after the recorded build."""
    record = runtime / NATIVE_PROVENANCE
    executable = runtime / NATIVE_EXECUTABLE
    if not record.is_file() or not executable.is_file():
        raise FileNotFoundError("Native Slicer build provenance or executable is missing; rebuild and reassemble Slicer")
    provenance = json.loads(record.read_text(encoding="utf-8"))
    if provenance.get("format_version") != 1:
        raise ValueError("Unsupported native Slicer build provenance")
    if provenance.get("native_source_sha256") != native_source_sha256(project_root):
        raise ValueError("Native Slicer source differs from the assembled binary provenance; rebuild Slicer")
    if provenance.get("native_executable_sha256") != file_sha256(executable):
        raise ValueError("Native Slicer executable differs from its build provenance")


def verify_portable_vc_runtime(
    runtime: Path, *, expected_hashes: dict[str, str] | None = None,
) -> None:
    """Reject a Slicer payload that depends on the host's older MSVC runtime."""
    expected_hashes = APP_LOCAL_VC_RUNTIME_HASHES if expected_hashes is None else expected_hashes
    for name, expected in expected_hashes.items():
        dll = runtime / "bin" / "Release" / name
        if not dll.is_file():
            raise FileNotFoundError(f"Required app-local VC runtime is missing: {dll}")
        if file_sha256(dll).lower() != expected.lower():
            raise ValueError(f"App-local VC runtime hash mismatch: {dll}")


def stage_current_startup(package_dir: Path, project_root: Path) -> str:
    """Overlay the authoritative source into the Slicer runtime and record its hash.

    The cached native runtime is immutable build input.  Never edit it to update
    a Python startup script: stage a fresh copy inside each package instead.
    """
    source = project_root / STARTUP_SOURCE
    runtime = package_dir / "payload" / STARTUP_RUNTIME
    plugin = package_dir / "payload/python" / STARTUP_SOURCE
    if not source.is_file():
        raise FileNotFoundError(f"Current Slicer startup source is missing: {source}")
    if not runtime.is_file():
        raise FileNotFoundError(f"Cached Slicer startup entry point is missing: {runtime}")
    if not plugin.is_file():
        raise FileNotFoundError(f"Packaged Slicer startup source is missing: {plugin}")
    source_hash = file_sha256(source)
    if file_sha256(plugin) != source_hash:
        raise ValueError("Packaged Slicer Python source differs from Developer Run")
    for relative in PRESENTATION_COMPANIONS:
        current = project_root / relative
        packaged = package_dir / "payload/python" / relative
        if not current.is_file() or not packaged.is_file():
            raise FileNotFoundError(f"Slicer presentation companion is missing: {relative}")
        if file_sha256(current) != file_sha256(packaged):
            raise ValueError(f"Packaged Slicer presentation differs from Developer Run: {relative}")
    shutil.copy2(source, runtime)
    if file_sha256(runtime) != source_hash:
        raise ValueError("Staged Slicer runtime startup differs from Developer Run")
    return source_hash


def verify_cache_matches_developer_runtime(
    project_root: Path, asset_root: Path, *, runtime_items: tuple[str, ...] = RUNTIME_ITEMS,
) -> None:
    """Reject a cached native/UI runtime that differs from the Developer Run.

    The startup script is overlaid later; all other Slicer runtime files must
    represent the same assembled application the developer actually launched.
    """
    developer = project_root / DEVELOPER_RUNTIME
    cached = asset_root / "slicer-runtime"
    if not developer.is_dir() or not cached.is_dir():
        raise FileNotFoundError("Developer Slicer runtime or cached Slicer runtime is missing")
    verify_native_build_provenance(project_root, developer)
    verify_native_build_provenance(project_root, cached)
    verify_portable_vc_runtime(developer)
    verify_portable_vc_runtime(cached)

    def selected_files(root: Path) -> dict[Path, Path]:
        result: dict[Path, Path] = {}
        for item in runtime_items:
            path = root / item
            if path.is_file():
                result[path.relative_to(root)] = path
            elif path.is_dir():
                for file in path.rglob("*"):
                    if not file.is_file() or "__pycache__" in file.parts or file.suffix in (".pyc", ".pyo"):
                        continue
                    result[file.relative_to(root)] = file
            else:
                raise FileNotFoundError(f"Slicer runtime item is missing: {path}")
        return result

    current_files = selected_files(developer)
    cached_files = selected_files(cached)
    if current_files.keys() != cached_files.keys():
        missing = sorted(str(path) for path in current_files.keys() - cached_files.keys())
        extra = sorted(str(path) for path in cached_files.keys() - current_files.keys())
        raise ValueError(f"Cached Slicer runtime file set differs from Developer Run: missing={missing[:5]}, extra={extra[:5]}")
    for relative, current in current_files.items():
        stored = cached_files[relative]
        if current.stat().st_size != stored.stat().st_size or file_sha256(current) != file_sha256(stored):
            raise ValueError(f"Cached Slicer runtime differs from Developer Run: {relative}")
