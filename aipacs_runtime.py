from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse


APP_NAME = "AIPacs"
USER_DATA_DIRNAME = "user_data"
USER_CONFIG_DIRNAME = "config"
MODULES_RUNTIME_DIRNAME = "modules_runtime"
INSTALLATION_PROFILE_FILENAME = "installation_profile.json"
USER_RUNTIME_PROFILE_FILENAME = "runtime_profile.json"
RESPECT_DEV_MODULE_PROFILE_ENV = "AIPACS_RESPECT_MODULE_PROFILE_IN_DEV"
QT_SOFTWARE_OPENGL_DLL_ENV = "AIPACS_QT_OPENGL_DLL"
VTK_OSMESA_DLL_ENV = "AIPACS_VTK_OSMESA_DLL"
SOFTWARE_GRAPHICS_RUNTIME_DIRNAME = "graphics_runtime"
GRAPHICS_EXECUTION_GPU = "cpu_physical_gpu"
GRAPHICS_EXECUTION_SOFTWARE = "cpu_software_opengl"
SAFE_VIEWER_BACKEND_ENV = "AIPACS_FORCE_SAFE_VIEWER_BACKEND"
SAFE_VIEWER_BACKEND_DEFAULT = "pydicom_qt"
MODULE_PACKAGE_FORMAT_VERSION = 1
MODULE_PACKAGE_MANIFEST_FILENAME = "module_package.json"
MODULE_PACKAGE_FEED_FILENAME = "module_package_feed.json"
MODULE_PACKAGE_PAYLOAD_DIRNAME = "payload"
MODULE_PACKAGE_REGISTRY_DIRNAME = "module_registry"
MODULE_PACKAGE_DOWNLOADS_DIRNAME = "module_packages"
UPDATE_FEED_FILENAME = "update_feed.json"
UPDATE_SOURCES_FILENAME = "update_sources.json"
UPDATES_CACHE_DIRNAME = "updates"
CORE_COMPONENT_ID = "core_app"
CORE_COMPONENT_TITLE = "AIPacs Core"

OPTIONAL_MODULE_PATH_HANDLES: list[Any] = []

MODULE_CATALOG: list[dict[str, Any]] = [
    {
        "id": "viewer",
        "title": "Viewer",
        "tier": "basic",
        "default_enabled": True,
        "component": "basic\\viewer",
    },
    {
        "id": "download_manager",
        "title": "Download Manager",
        "tier": "basic",
        "default_enabled": True,
        "component": "basic\\download_manager",
    },
    {
        "id": "zeta_boost",
        "title": "ZetaBoost",
        "tier": "basic",
        "default_enabled": True,
        "component": "basic\\zeta_boost",
    },
    {
        "id": "education",
        "title": "Education Module",
        "tier": "basic",
        "default_enabled": True,
        "component": "basic\\education",
        "package_kind": "core",
        "package_python_paths": ["python"],
        "package_sources": ["modules/education"],
        "healthcheck_import": "modules.education.education_main_widget",
    },
    {
        "id": "stitching",
        "title": "Stitching Module",
        "tier": "basic",
        "default_enabled": True,
        "component": "basic\\stitching",
        "package_kind": "core",
        "package_python_paths": ["python"],
        "package_sources": ["modules/stitching"],
        "healthcheck_import": "modules.stitching",
    },
    {
        "id": "offline_cloud_server",
        "title": "Offline Cloud Server",
        "tier": "basic",
        "default_enabled": True,
        "component": "basic\\offline_cloud_server",
        "package_kind": "core",
        "package_python_paths": ["python"],
        "package_sources": ["modules/offline_cloud_server"],
        "healthcheck_import": "modules.offline_cloud_server.service",
    },
    {
        # ADR-0003 (2026-06-10): Identity ships in the CORE bundle — it is shared
        # infrastructure (account pill, OAuth custody, future aipacs_web pairing /
        # licensing provider), required even when Consultation is not purchased.
        "id": "identity",
        "title": "Identity & Accounts",
        "tier": "basic",
        "default_enabled": True,
        "component": "basic\\identity",
        "package_kind": "core",
        "package_python_paths": ["python"],
        "package_sources": ["modules/Identity"],
        "healthcheck_import": "modules.Identity.feature_flags",
        # Declared so dependency validation can read the flag VALUE and name
        # "Identity is switched off" precisely. Identity is basic tier, so the
        # install-time auto-enable path never runs for it — this is read-only
        # metadata here.
        "feature_flag": {"config": "identity/identity.json", "key": "enabled"},
    },
    {
        "id": "data_analysis",
        "title": "Data Analysis",
        "tier": "optional",
        "default_enabled": True,
        "component": "basic\\data_analysis",
        "package_kind": "bundled_unlock",
        "package_python_paths": ["python"],
        "package_sources": ["modules/data_analysis"],
        "healthcheck_import": "modules.data_analysis",
    },
    {
        "id": "advanced_mpr",
        "title": "Advanced MPR",
        "tier": "optional",
        "default_enabled": False,
        "component": "optional\\advanced_mpr",
        "payload_dir": "advanced_mpr",
        "package_kind": "runtime_payload",
        "package_python_paths": [],
        "healthcheck_path": "AIPacsAdvancedViewer.exe",
    },
    {
        "id": "printing",
        "title": "Printing Module",
        "tier": "optional",
        "default_enabled": False,
        "component": "optional\\printing",
        "package_kind": "bundled_unlock",
        "package_python_paths": ["python"],
        "package_sources": ["modules/printing"],
        "healthcheck_import": "modules.printing.ui.printing_widget",
    },
    {
        "id": "run_cd",
        "title": "Run CD Module",
        "tier": "optional",
        "default_enabled": False,
        "component": "optional\\run_cd",
        "payload_dir": "run_cd",
        "package_kind": "bundled_unlock",
        "package_python_paths": ["python"],
        "package_sources": ["modules/cd_burner"],
        "healthcheck_import": "modules.cd_burner.cd_burn_dialog",
    },
    {
        "id": "web_browser",
        "title": "Web Browser Module",
        "tier": "optional",
        "default_enabled": False,
        "component": "optional\\web_browser",
        "package_kind": "bundled_unlock",
        "package_python_paths": ["python"],
        "package_sources": ["modules/web_browser"],
        "healthcheck_import": "modules.web_browser",
    },
    {
        "id": "echomind",
        "title": "EchoMind Module",
        "tier": "optional",
        "default_enabled": False,
        "component": "optional\\echomind",
        "package_kind": "bundled_unlock",
        "package_python_paths": ["python"],
        "package_sources": ["modules/EchoMind"],
        "healthcheck_import": "modules.EchoMind.settings_store",
    },
    {
        # ADR-0003 (2026-06-10): the purchasable Online Consultation module.
        # Ships the engine (modules/cloud_consultation); the Education tab that
        # composes it ships with the education core package, and modules/Identity
        # ships in core (see the "identity" entry above). The user-facing gate is
        # modules.education.online_consultation.online_consultation_available()
        # = both feature flags AND is_module_enabled("consultation").
        "id": "consultation",
        "title": "Online Consultation",
        "tier": "optional",
        "default_enabled": False,
        "component": "optional\\consultation",
        "package_kind": "bundled_unlock",
        "package_python_paths": ["python"],
        "package_sources": ["modules/cloud_consultation"],
        "healthcheck_import": "modules.cloud_consultation.feature_flags",
    },
    {
        # The manager console for the ai-pacs.com consultation chat. A SECOND
        # CLIENT of an existing backend, not a second chat system: every
        # conversation, rule and piece of state lives in the Laravel
        # PatientChat module and is reached over /api/v1/chat/*.
        #
        # Depends on Identity (core) for the Sanctum token — it has no auth of
        # its own, and the user-facing gate
        # modules.aipacs_chat.feature_flags.aipacs_chat_available() checks the
        # identity flag, this module's flag AND this catalog entry together.
        "id": "aipacs_chat",
        "title": "AiPacs Chat",
        "tier": "optional",
        "default_enabled": False,
        "component": "optional\\aipacs_chat",
        "package_kind": "bundled_unlock",
        "package_python_paths": ["python"],
        "package_sources": ["modules/aipacs_chat"],
        "healthcheck_import": "modules.aipacs_chat.feature_flags",
        # Module-install reliability (2026-08-22): ``requires`` is validated by
        # validate_module_installation() with a NAMED diagnostic ("cannot start
        # because ..."), and ``feature_flag`` is switched ON automatically after
        # a successful, VERIFIED install (installer checkbox, Settings package/
        # folder/URL installs and feed updates all funnel through
        # install_module_package). Without this, a freshly installed module
        # still refused to open because its own flag ships force-disabled
        # (builder/config_sanitizer.py) — the 2026-08-22 "icon visible, module
        # 'not installed correctly'" bug. Other modules opt in by declaring the
        # same two keys.
        "requires": ["identity"],
        "feature_flag": {"config": "aipacs_chat/aipacs_chat.json", "key": "enabled"},
    },
]


def is_frozen() -> bool:
    """
    Detect if running in a frozen/compiled environment.
    
    Supports:
    - PyInstaller (sys.frozen = True)
    - Nuitka (via __compiled__ marker or sys.__nuitka__ flag)
    - Dev mode (.py files)
    
    Returns:
        True if frozen/compiled, False if running from source
    """
    # PyInstaller detection
    if getattr(sys, "frozen", False):
        return True
    
    # Nuitka detection - check multiple possible markers
    # Nuitka may set sys.__nuitka__ or inject __compiled__ into builtins
    if hasattr(sys, "__nuitka__"):
        return True
    
    try:
        import builtins
        if getattr(builtins, "__compiled__", False):
            return True
    except Exception:
        pass
    
    # Heuristic fallback: if sys.argv[0] is not a .py file, likely frozen
    # (but be careful - could be .pyc or other)
    if sys.argv and not sys.argv[0].endswith((".py", ".pyc")):
        # Additional check: executable path should look like an .exe on Windows
        if sys.platform == "win32" and sys.executable.endswith(".exe"):
            # Final guard: make sure we're not just running 'python.exe script.py'
            if not sys.argv[0].endswith(".exe"):
                return False
            return True
    
    return False


def bundle_root() -> Path:
    """
    Get the root directory of the frozen bundle.
    
    In frozen mode:
    - PyInstaller: returns sys._MEIPASS (extraction directory)
    - Nuitka standalone: returns directory containing the executable
    
    In dev mode:
    - Returns the directory containing this file (project root)
    
    Returns:
        Path to the bundle root
    """
    if is_frozen():
        # PyInstaller sets sys._MEIPASS to the extraction directory
        if hasattr(sys, "_MEIPASS"):
            return Path(sys._MEIPASS)
        
        # Nuitka standalone: executable is in the bundle root
        # (no extraction, everything is in the .dist folder)
        return Path(sys.executable).resolve().parent
    
    # Dev mode: this file's parent directory
    return Path(__file__).resolve().parent


def install_root() -> Path:
    if is_frozen():
        exe_dir = Path(sys.executable).resolve().parent
        # For installer layout:
        #   {app}\Engine\AIPacs.exe
        # keep install_root at {app} so User Data remains parallel to Engine.
        if exe_dir.name.lower() == "engine":
            return exe_dir.parent
        return exe_dir
    return bundle_root()


def bundled_config_root() -> Path:
    return bundle_root() / "config"


def modules_runtime_root() -> Path:
    if is_frozen() and sys.platform == "win32":
        return local_state_root() / MODULES_RUNTIME_DIRNAME
    return install_root() / MODULES_RUNTIME_DIRNAME


def legacy_modules_runtime_root() -> Path:
    return install_root() / MODULES_RUNTIME_DIRNAME


def modules_runtime_search_roots() -> list[Path]:
    roots: list[Path] = []
    for candidate in (modules_runtime_root(), legacy_modules_runtime_root()):
        if candidate not in roots:
            roots.append(candidate)
    return roots


def module_registry_root() -> Path:
    if is_frozen() and sys.platform == "win32":
        return roaming_config_root() / MODULE_PACKAGE_REGISTRY_DIRNAME
    return bundle_root() / "generated-files" / MODULE_PACKAGE_REGISTRY_DIRNAME


def module_downloads_root() -> Path:
    if is_frozen() and sys.platform == "win32":
        return local_state_root() / MODULE_PACKAGE_DOWNLOADS_DIRNAME
    return bundle_root() / "generated-files" / MODULE_PACKAGE_DOWNLOADS_DIRNAME


def bundled_module_packages_search_roots() -> list[Path]:
    roots: list[Path] = []
    candidates: list[Path] = []
    # Installer-deployed packages live in ProgramData (shared across users, writable without elevation)
    if is_frozen() and sys.platform == "win32":
        candidates.append(
            Path(os.environ.get("PROGRAMDATA", "C:/ProgramData"))
            / APP_NAME
            / MODULE_PACKAGE_DOWNLOADS_DIRNAME
        )
    # Legacy / dev fallbacks
    candidates += [
        install_root() / MODULE_PACKAGE_DOWNLOADS_DIRNAME,
        bundle_root() / MODULE_PACKAGE_DOWNLOADS_DIRNAME,
    ]
    for candidate in candidates:
        if candidate not in roots:
            roots.append(candidate)
    return roots


def bundled_module_packages_root() -> Path:
    return bundled_module_packages_search_roots()[0]


def _win_dir(env_name: str, fallback_suffix: tuple[str, ...]) -> Path:
    value = os.environ.get(env_name)
    if value:
        return Path(value)
    return Path.home().joinpath(*fallback_suffix)


def _is_path_writable(path: Path) -> bool:
    """Best-effort writable probe for runtime storage paths."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".aipacs_write_probe.tmp"
        with probe.open("w", encoding="utf-8") as handle:
            handle.write("ok")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def local_state_root() -> Path:
    if is_frozen() and sys.platform == "win32":
        return _win_dir("LOCALAPPDATA", ("AppData", "Local")) / APP_NAME
    return install_root()


def roaming_config_root() -> Path:
    if is_frozen() and sys.platform == "win32":
        return _win_dir("APPDATA", ("AppData", "Roaming")) / APP_NAME / USER_CONFIG_DIRNAME
    return bundled_config_root()


def program_data_config_root() -> Path:
    """System-wide deployment config root — writable by installer, readable by all users."""
    if is_frozen() and sys.platform == "win32":
        return Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / APP_NAME / USER_CONFIG_DIRNAME
    return bundled_config_root()


def user_data_root() -> Path:
    if is_frozen() and sys.platform == "win32":
        # Canonical installed location: Program Files\AIPacs\User Data.
        # If permissions are missing on a specific machine, fall back to the
        # per-user LocalAppData path so runtime writes still succeed.
        preferred = install_root() / "User Data"
        if _is_path_writable(preferred):
            return preferred
        return local_state_root() / USER_DATA_DIRNAME
    return bundle_root() / USER_DATA_DIRNAME


def advanced_mpr_runtime_root() -> Path:
    if is_frozen():
        for root in modules_runtime_search_roots():
            candidate = root / "advanced_mpr"
            if candidate.exists():
                return candidate
        return modules_runtime_root() / "advanced_mpr"
    return (
        bundle_root()
        / "modules"
        / "mpr"
        / "advanced_3d_slicer"
        / "slicer_custom_app"
        / "NewMPR2Slicer"
        / "build"
    )


def installation_profile_path() -> Path:
    return program_data_config_root() / INSTALLATION_PROFILE_FILENAME


def user_runtime_profile_path() -> Path:
    if is_frozen() and sys.platform == "win32":
        return roaming_config_root() / USER_RUNTIME_PROFILE_FILENAME
    return bundle_root() / "generated-files" / USER_RUNTIME_PROFILE_FILENAME


def update_sources_config_path() -> Path:
    if is_frozen() and sys.platform == "win32":
        return roaming_config_root() / UPDATE_SOURCES_FILENAME
    return bundled_config_root() / UPDATE_SOURCES_FILENAME


def updates_cache_root() -> Path:
    if is_frozen() and sys.platform == "win32":
        return local_state_root() / UPDATES_CACHE_DIRNAME
    return bundle_root() / "generated-files" / UPDATES_CACHE_DIRNAME


def module_defaults() -> dict[str, bool]:
    return {item["id"]: bool(item.get("default_enabled", False)) for item in MODULE_CATALOG}


def module_catalog_map() -> dict[str, dict[str, Any]]:
    return {str(item["id"]): item for item in MODULE_CATALOG}


def module_package_defaults() -> dict[str, dict[str, Any]]:
    packages: dict[str, dict[str, Any]] = {}
    for item in MODULE_CATALOG:
        module_id = str(item["id"])
        package_kind = str(item.get("package_kind") or "core")
        tier = str(item.get("tier") or "optional")
        packages[module_id] = {
            "module_id": module_id,
            "title": str(item.get("title") or module_id),
            "tier": tier,
            "package_kind": package_kind,
            "status": "core" if tier == "basic" else "not_installed",
            "installed_version": "",
            "installed_from": "core_bundle" if tier == "basic" else "",
            "installed_at_utc": "",
            "runtime_path": "",
            "archive_name": "",
            "requires_restart": bool(tier == "optional"),
            "warning": "",
        }
    return packages


def development_module_defaults() -> dict[str, bool]:
    """Expose the full workstation surface area during source/developer runs."""
    return {item["id"]: True for item in MODULE_CATALOG}


def _should_enforce_module_profile() -> bool:
    if is_frozen():
        return True
    return os.environ.get(RESPECT_DEV_MODULE_PROFILE_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def default_installation_profile() -> dict[str, Any]:
    return {
        "app_name": APP_NAME,
        "app_version": "",
        "generated_at_utc": "",
        "installer": {
            "current_version": "",
            "detected_existing_version": "",
            "install_action": "fresh_install",
            "should_update": False,
        },
        "modules": module_defaults(),
        "module_packages": module_package_defaults(),
        "graphics": {
            "user_declared_gpu": False,
            "preferred_mode": "cpu_safe",
            "last_detected_gpu": False,
            "last_probe_backend": "",
            "last_probe_device": "",
            "last_probe_utc": "",
            "last_execution_mode": "",
            "last_software_rendering_status": "",
            "last_software_rendering_warning": "",
        },
    }


def default_update_sources() -> dict[str, Any]:
    return {
        "app_name": APP_NAME,
        "active_source_id": "primary",
        "sources": [
            {
                "id": "primary",
                "title": "Primary Update Source",
                "type": "file",
                "location": "",
                "channel": "stable",
            }
        ],
    }


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8")) or {}
            if isinstance(payload, dict):
                return _deep_merge(default, payload)
    except Exception:
        pass
    return deepcopy(default)


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_installation_profile() -> dict[str, Any]:
    return _load_json(installation_profile_path(), default_installation_profile())


def load_update_sources() -> dict[str, Any]:
    primary_path = update_sources_config_path()
    fallback_path = bundled_config_root() / UPDATE_SOURCES_FILENAME
    if primary_path.exists():
        return _load_json(primary_path, default_update_sources())
    if fallback_path != primary_path and fallback_path.exists():
        return _load_json(fallback_path, default_update_sources())
    return deepcopy(default_update_sources())


def save_update_sources(payload: dict[str, Any]) -> dict[str, Any]:
    merged = _deep_merge(default_update_sources(), payload or {})
    save_json(update_sources_config_path(), merged)
    return merged


def load_runtime_profile() -> dict[str, Any]:
    return _load_json(user_runtime_profile_path(), load_installation_profile())


def save_runtime_profile(patch: dict[str, Any]) -> dict[str, Any]:
    profile = _deep_merge(load_runtime_profile(), patch or {})
    profile["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    save_json(user_runtime_profile_path(), profile)
    return profile


def configured_module_map(profile: dict[str, Any] | None = None) -> dict[str, bool]:
    payload = profile or load_runtime_profile()
    modules = payload.get("modules") or {}
    merged = module_defaults()
    for key, value in modules.items():
        merged[str(key)] = bool(value)
    return merged


def module_package_map(profile: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    payload = profile or load_runtime_profile()
    packages = payload.get("module_packages") or {}
    merged = module_package_defaults()
    for key, value in packages.items():
        module_id = str(key)
        if not isinstance(value, dict):
            continue
        current = merged.get(module_id, {"module_id": module_id})
        merged[module_id] = _deep_merge(current, value)
    return merged


def installed_module_manifest_path(module_id: str) -> Path:
    return module_registry_root() / f"{module_id}.json"


def module_runtime_dir(module_id: str) -> Path:
    return modules_runtime_root() / module_id


def module_runtime_search_dirs(module_id: str) -> list[Path]:
    paths: list[Path] = []
    for root in modules_runtime_search_roots():
        candidate = root / module_id
        if candidate not in paths:
            paths.append(candidate)
    return paths


def _load_module_manifest_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def load_installed_module_manifest(module_id: str) -> dict[str, Any] | None:
    manifest = _load_module_manifest_file(installed_module_manifest_path(module_id))
    if manifest:
        return manifest
    for runtime_dir in module_runtime_search_dirs(module_id):
        manifest = _load_module_manifest_file(runtime_dir / MODULE_PACKAGE_MANIFEST_FILENAME)
        if manifest:
            return manifest
    return None


def module_python_runtime_paths(profile: dict[str, Any] | None = None) -> list[Path]:
    packages = module_package_map(profile)
    paths: list[Path] = []
    for module_id, state in packages.items():
        manifest = load_installed_module_manifest(module_id)
        if not manifest:
            continue
        runtime_dir = module_runtime_dir(module_id)
        if not runtime_dir.exists():
            for candidate in module_runtime_search_dirs(module_id):
                if candidate.exists():
                    runtime_dir = candidate
                    break
        python_paths = manifest.get("python_paths") or state.get("python_paths") or []
        for relative in python_paths:
            candidate = runtime_dir / str(relative)
            if candidate.exists():
                _append_unique_path(paths, candidate)
    return paths


def activate_optional_module_runtime(profile: dict[str, Any] | None = None) -> list[str]:
    added: list[str] = []
    runtime_paths = module_python_runtime_paths(profile)
    if not runtime_paths:
        return added

    current_path = os.environ.get("PATH", "")
    current_parts = [part for part in current_path.split(os.pathsep) if part]
    current_lower = {part.lower() for part in current_parts}
    path_updates: list[str] = []

    for candidate in runtime_paths:
        candidate_str = str(candidate)
        # Append (not prepend) so the engine's bundled `modules` package always wins
        # for any module name it provides. Optional plugin payloads must be additive
        # only — they may contribute NEW modules but must never shadow an existing
        # engine package. Prepending caused `modules.mpr` from advanced_mpr's
        # payload (which only contains advanced_3d_slicer) to mask the engine's
        # complete `modules.mpr` tree, breaking imports of `modules.mpr.curved_mpr`,
        # `zeta_mpr`, and `orthogonal`. See R24 in copilot-instructions.md.
        if candidate_str not in sys.path:
            sys.path.append(candidate_str)
            added.append(candidate_str)
        parent_str = str(candidate.resolve())
        if parent_str.lower() not in current_lower:
            path_updates.append(parent_str)
            current_lower.add(parent_str.lower())
        if hasattr(os, "add_dll_directory"):
            try:
                OPTIONAL_MODULE_PATH_HANDLES.append(os.add_dll_directory(parent_str))
            except Exception:
                pass

        modules_dir = candidate / "modules"
        if modules_dir.exists():
            try:
                import modules as modules_package

                package_paths = list(getattr(modules_package, "__path__", []))
                if str(modules_dir) not in package_paths:
                    # Append so engine `modules\mpr\__init__.py` (regular package)
                    # is found before any plugin-shipped `modules\mpr\__init__.py`
                    # and remains the authoritative resolver for `modules.mpr.*`.
                    modules_package.__path__.append(str(modules_dir))

                # Runtime sanity: verify the append did not move engine paths
                # away from index 0.  The engine path must always be first in
                # modules.__path__ so the PYZ/on-disk package beats plugin copies.
                final_paths = list(getattr(modules_package, "__path__", []))
                if final_paths and str(modules_dir) == final_paths[0]:
                    import logging as _logging
                    _logging.getLogger(__name__).warning(
                        "[R24_SANITY] activate_optional_module_runtime: plugin modules dir "
                        "ended up at index 0 of modules.__path__ — this should not happen "
                        "with append-only logic.  Path: %s  Full path list: %s",
                        modules_dir,
                        final_paths[:5],
                    )
            except Exception:
                pass

    if path_updates:
        os.environ["PATH"] = os.pathsep.join([*path_updates, *current_parts])
    return added


def _package_record(
    module_id: str,
    *,
    manifest: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    catalog = module_catalog_map().get(module_id, {})
    package_state = dict(state or module_package_map().get(module_id, {}))
    effective_manifest = manifest or load_installed_module_manifest(module_id) or {}
    configured = configured_module_map()
    runtime_dir = module_runtime_dir(module_id)
    if not runtime_dir.exists():
        for candidate in module_runtime_search_dirs(module_id):
            if candidate.exists():
                runtime_dir = candidate
                break

    package_kind = str(
        effective_manifest.get("package_kind")
        or package_state.get("package_kind")
        or catalog.get("package_kind")
        or "core"
    )
    tier = str(catalog.get("tier") or package_state.get("tier") or "optional")
    installed = bool(tier == "basic")
    if package_kind == "runtime_payload":
        payload_anchor = str(effective_manifest.get("healthcheck_path") or catalog.get("healthcheck_path") or "").strip()
        installed = runtime_dir.exists() and (not payload_anchor or (runtime_dir / payload_anchor).exists())
    elif effective_manifest:
        installed = True
    elif package_state.get("status") in {"installed", "core"}:
        installed = True

    # Keep FAILURE states visible (2026-08-22): a profile that recorded
    # install_failed / install_incomplete must not be flattened to a generic
    # "installed"/"not_installed" — the Settings table and diagnostics dialogs
    # read this status to tell the user WHAT went wrong. The failure status
    # wins even when package files are present (install_incomplete = files
    # copied, verification failed); a later SUCCESSFUL install overwrites the
    # profile status with "installed" and clears it.
    state_status = str(package_state.get("status") or "")
    if tier == "basic":
        status = "core"
    elif state_status in {"install_failed", "install_incomplete"}:
        status = state_status
    elif installed:
        status = "installed"
    else:
        status = "not_installed"

    record = {
        "module_id": module_id,
        "title": str(catalog.get("title") or package_state.get("title") or module_id),
        "tier": tier,
        "package_kind": package_kind,
        "enabled": bool(configured.get(module_id, False) if enabled is None else enabled),
        "installed": bool(installed),
        "status": status,
        "runtime_path": str(runtime_dir if runtime_dir.exists() else ""),
        "installed_version": str(
            effective_manifest.get("version")
            or package_state.get("installed_version")
            or (current_app_version() if tier == "basic" else "")
            or ""
        ),
        "installed_from": str(
            effective_manifest.get("installed_from")
            or package_state.get("installed_from")
            or ("core_bundle" if tier == "basic" else "")
            or ""
        ),
        "installed_at_utc": str(package_state.get("installed_at_utc") or ""),
        "archive_name": str(package_state.get("archive_name") or ""),
        "requires_restart": bool(
            effective_manifest.get("requires_restart", package_state.get("requires_restart", tier == "optional"))
        ),
        "healthcheck_import": str(
            effective_manifest.get("healthcheck_import")
            or catalog.get("healthcheck_import")
            or ""
        ),
        "healthcheck_path": str(
            effective_manifest.get("healthcheck_path")
            or catalog.get("healthcheck_path")
            or ""
        ),
        "warning": str(package_state.get("warning") or ""),
    }
    return record


def module_installation_statuses(profile: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    effective_profile = profile or load_runtime_profile()
    packages = module_package_map(effective_profile)
    configured = configured_module_map(effective_profile)
    records = []
    for item in MODULE_CATALOG:
        module_id = str(item["id"])
        records.append(
            _package_record(
                module_id,
                state=packages.get(module_id),
                enabled=bool(configured.get(module_id, False)),
            )
        )
    return records


def current_app_version(profile: dict[str, Any] | None = None) -> str:
    effective_profile = profile or load_runtime_profile()
    version = str(effective_profile.get("app_version") or "").strip()
    if version:
        return version

    install_profile = load_installation_profile()
    version = str(install_profile.get("app_version") or "").strip()
    if version:
        return version

    pyproject_path = bundle_root() / "pyproject.toml"
    if pyproject_path.exists():
        try:
            if sys.version_info >= (3, 11):
                import tomllib
            else:
                import tomli as tomllib  # type: ignore

            payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
            return str((payload.get("project") or {}).get("version") or "").strip()
        except Exception:
            return ""
    return ""


def compare_release_versions(left: str, right: str) -> int:
    left_parts = [int(part) if part.isdigit() else 0 for part in str(left or "").strip().split(".") if part != ""]
    right_parts = [int(part) if part.isdigit() else 0 for part in str(right or "").strip().split(".") if part != ""]
    size = max(len(left_parts), len(right_parts), 1)
    left_parts.extend([0] * (size - len(left_parts)))
    right_parts.extend([0] * (size - len(right_parts)))
    for left_part, right_part in zip(left_parts, right_parts):
        if left_part < right_part:
            return -1
        if left_part > right_part:
            return 1
    return 0


def _native_machine_name() -> str:
    """Host machine per IsWow64Process2 ("ARM64"/"AMD64"/…); "" when unknown.

    Local, stdlib-only twin of PacsClient.utils.runtime_arch_log (this module
    must not import PacsClient — it is imported BY it). On an ARM64 host an
    x64-emulated process still sees the TRUE host machine here, which is what
    per-architecture update selection needs.
    """
    if sys.platform != "win32":
        return ""
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        if not hasattr(kernel32, "IsWow64Process2"):
            return ""
        process_machine = ctypes.c_ushort(0)
        native_machine = ctypes.c_ushort(0)
        if not kernel32.IsWow64Process2(
            kernel32.GetCurrentProcess(),
            ctypes.byref(process_machine),
            ctypes.byref(native_machine),
        ):
            return ""
        return {0x8664: "AMD64", 0xAA64: "ARM64", 0x014C: "x86", 0x01C4: "ARMNT"}.get(
            native_machine.value, ""
        )
    except Exception:
        return ""


def native_host_arch() -> str:
    """Best-effort HOST architecture ("ARM64"/"AMD64"/"x86"/""), robust.

    IsWow64Process2 is authoritative but on some Windows-on-ARM builds it
    returns 0/unknown from an emulated x64 process (observed live on the
    Snapdragon test machine 2026-07-08 — native_arch came back empty). Fall
    back to signals that survive emulation: PROCESSOR_ARCHITEW6432 (set by WOW),
    platform.machine() (Python 3.13 reports the true host even when emulated),
    and the PROCESSOR_IDENTIFIER string ("ARMv8 … Qualcomm"). Stdlib only.
    """
    native = _native_machine_name()
    if native:
        return native
    try:
        alt = (os.environ.get("PROCESSOR_ARCHITEW6432") or "").upper()
        if alt in ("ARM64", "AMD64", "X86"):
            return alt
        import platform as _pf

        mach = (_pf.machine() or "").upper()
        if mach in ("ARM64", "AARCH64"):
            return "ARM64"
        ident = (os.environ.get("PROCESSOR_IDENTIFIER") or "").upper()
        if "ARM" in ident or "QUALCOMM" in ident or "SNAPDRAGON" in ident or "ORYON" in ident:
            return "ARM64"
        if mach in ("AMD64", "X86_64"):
            return "AMD64"
    except Exception:
        pass
    return ""


def process_view_arch() -> str:
    """What THIS process runs as ("AMD64"/"X86"/"ARM64"): the emulated view.

    An x64 process under Windows-on-ARM emulation reports AMD64 here (via
    PROCESSOR_ARCHITECTURE) even though the host is ARM64 — that mismatch is
    the emulation tell.
    """
    proc = (os.environ.get("PROCESSOR_ARCHITECTURE") or "").upper()
    if proc:
        return proc
    return "AMD64" if sys.maxsize > 2**32 else "X86"


def is_windows_on_arm_emulated() -> bool:
    """True when an x64/x86 build runs under Windows-on-ARM (Prism) emulation.

    This is THE gate for the WoA graphics + runtime profile. Must be cheap +
    never raise (called at graphics-config time, before logging). The decisive
    live case: bundled software OpenGL (llvmpipe) executes a SIMD instruction
    Prism can't emulate → 0xc000001d ILLEGAL INSTRUCTION at VTK init, while the
    hardware D3D12/Adreno GL path works — so the "safe = software" default is
    INVERTED here and this flag flips it (see build_windows_graphics_environment).
    """
    if sys.platform != "win32":
        return False
    try:
        return native_host_arch() == "ARM64" and process_view_arch() in ("AMD64", "X86", "IA64")
    except Exception:
        return False


def resolve_source_location(source: dict[str, Any], native_arch: str | None = None) -> str:
    """Per-architecture update location (ARM64 plan §4, 2026-07-07).

    A source entry may carry ``"location_by_arch": {"x64": ..., "arm64": ...}``.
    Selection keys on the HOST machine (so an x64 build running under
    Windows-on-ARM emulation is offered the arm64 package = the migration
    path); entries without the key — every existing config — resolve exactly
    as before via ``location``. Pure given ``native_arch``; never raises.
    """
    legacy = str(source.get("location") or "").strip()
    by_arch = source.get("location_by_arch")
    if not isinstance(by_arch, dict) or not by_arch:
        return legacy
    if native_arch is None:
        native_arch = _native_machine_name()
    key = "arm64" if str(native_arch or "").strip().upper() == "ARM64" else "x64"
    picked = str(by_arch.get(key) or "").strip()
    return picked or legacy


def active_update_source() -> dict[str, Any]:
    payload = load_update_sources()
    active_id = str(payload.get("active_source_id") or "").strip()
    sources = payload.get("sources") or []

    def _with_arch_location(source: dict[str, Any]) -> dict[str, Any]:
        out = dict(source)
        resolved = resolve_source_location(source)
        if resolved:
            out["location"] = resolved
        return out

    if isinstance(sources, list):
        for source in sources:
            if not isinstance(source, dict):
                continue
            if str(source.get("id") or "").strip() == active_id:
                return _with_arch_location(source)
        for source in sources:
            if isinstance(source, dict):
                return _with_arch_location(source)
    return {"id": "", "title": "", "type": "file", "location": "", "channel": "stable"}


def build_profile() -> str:
    """Build profile: "standard" (default) or "arm64_lite" (ARM64 plan §5).

    The arm64-lite package is the FAST-only native Windows-on-ARM build (the
    FAST domain is VTK-free by architecture). Resolution: env
    ``AIPACS_BUILD_PROFILE`` override → installation profile ``build_profile``
    key (stamped by the arm64 installer) → "standard". Never raises.
    """
    try:
        env = os.environ.get("AIPACS_BUILD_PROFILE", "").strip().lower()
        if env in ("standard", "arm64_lite"):
            return env
        profile = load_installation_profile()
        value = str(profile.get("build_profile") or "").strip().lower()
        if value in ("standard", "arm64_lite"):
            return value
    except Exception:
        pass
    return "standard"


def vtk_features_available() -> bool:
    """False on the arm64-lite build: VTK-dependent modules (Standard/Advanced
    MPR, 3D, dental/curved MPR) are not shipped there until the Phase-2 VTK
    win_arm64 wheel lands. The standard build is unaffected (always True)."""
    return build_profile() != "arm64_lite"


def _source_reference(source: str | Path | None = None) -> dict[str, Any]:
    if source is None:
        active = active_update_source()
        return {
            "id": str(active.get("id") or "").strip(),
            "title": str(active.get("title") or "").strip(),
            "type": str(active.get("type") or "file").strip().lower(),
            "location": str(active.get("location") or "").strip(),
            "channel": str(active.get("channel") or "stable").strip() or "stable",
        }

    location = str(source).strip()
    parsed = urlparse(location)
    source_type = "url" if parsed.scheme in {"http", "https"} else "file"
    return {
        "id": "manual",
        "title": "Manual Update Source",
        "type": source_type,
        "location": location,
        "channel": "manual",
    }


def _resolve_feed_location(location: str) -> tuple[str, str]:
    reference = str(location or "").strip()
    if not reference:
        raise FileNotFoundError("No update source is configured.")

    parsed = urlparse(reference)
    if parsed.scheme in {"http", "https"}:
        if parsed.path.lower().endswith(".json"):
            base_location = reference.rsplit("/", 1)[0] + "/"
            return reference, base_location
        normalized = reference.rstrip("/") + "/"
        return urljoin(normalized, UPDATE_FEED_FILENAME), normalized

    path = Path(reference)
    if path.is_dir():
        feed_path = path / UPDATE_FEED_FILENAME
        return str(feed_path), str(path)
    if path.is_file():
        if path.name.lower() == UPDATE_FEED_FILENAME.lower():
            return str(path), str(path.parent)
        raise FileNotFoundError(f"Unsupported update source file: {path}")
    raise FileNotFoundError(str(path))


def _load_json_from_reference(reference: str) -> dict[str, Any]:
    parsed = urlparse(reference)
    if parsed.scheme in {"http", "https"}:
        with urllib.request.urlopen(reference, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8")) or {}
    else:
        payload = json.loads(Path(reference).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("Update feed must be a JSON object.")
    return payload


def load_update_feed(source: str | Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    reference = _source_reference(source)
    feed_location, base_location = _resolve_feed_location(reference["location"])
    feed = _load_json_from_reference(feed_location)
    if str(feed.get("app_name") or APP_NAME) != APP_NAME:
        raise ValueError(f"Update feed targets {feed.get('app_name')!r}, expected {APP_NAME!r}.")

    feed.setdefault("app_name", APP_NAME)
    feed.setdefault("channel", reference.get("channel") or "stable")
    if not isinstance(feed.get("components"), list):
        feed["components"] = []

    core_entry = feed.get("core") or {}
    if not isinstance(core_entry, dict):
        core_entry = {}
    core_entry.setdefault("module_id", CORE_COMPONENT_ID)
    core_entry.setdefault("title", CORE_COMPONENT_TITLE)
    core_entry.setdefault("release_version", str(feed.get("version") or ""))
    feed["core"] = core_entry

    context = {
        "id": reference["id"],
        "title": reference["title"],
        "type": reference["type"],
        "location": reference["location"],
        "channel": reference["channel"],
        "feed_location": feed_location,
        "base_location": base_location,
    }
    return context, feed


def resolve_update_artifact_source(
    artifact_path: str,
    *,
    source: str | Path | None = None,
    context: dict[str, Any] | None = None,
) -> str:
    relative = str(artifact_path or "").strip().replace("\\", "/")
    if not relative:
        raise FileNotFoundError("Update artifact path is empty.")

    active_context = context
    if active_context is None:
        active_context, _ = load_update_feed(source)

    if active_context.get("type") == "url":
        return urljoin(str(active_context.get("base_location") or ""), relative)

    base_path = Path(str(active_context.get("base_location") or ""))
    return str((base_path / relative).resolve())


def current_component_versions(profile: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    effective_profile = profile or load_runtime_profile()
    app_version = current_app_version(effective_profile)
    components: dict[str, dict[str, Any]] = {
        CORE_COMPONENT_ID: {
            "component_id": CORE_COMPONENT_ID,
            "title": CORE_COMPONENT_TITLE,
            "current_version": app_version,
            "installed": bool(app_version),
            "delivery": "installer",
        }
    }

    for record in module_installation_statuses(effective_profile):
        module_id = str(record.get("module_id") or "")
        current_version = str(record.get("installed_version") or "").strip()
        if not current_version and str(record.get("tier") or "") == "basic":
            current_version = app_version
        components[module_id] = {
            "component_id": module_id,
            "title": str(record.get("title") or module_id),
            "current_version": current_version,
            "installed": bool(record.get("installed") or str(record.get("tier") or "") == "basic"),
            "delivery": "core_bundle" if str(record.get("tier") or "") == "basic" else "package",
            "record": record,
        }
    return components


def _build_update_status(current_version: str, available_version: str, *, installed: bool) -> str:
    if not available_version:
        return "unknown"
    if not current_version:
        return "available" if not installed else "unknown"

    comparison = compare_release_versions(current_version, available_version)
    if comparison < 0:
        return "update_available"
    if comparison > 0:
        return "newer_than_feed"
    return "up_to_date"


def summarize_available_updates(
    source: str | Path | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context, feed = load_update_feed(source)
    current_versions = current_component_versions(profile)

    core_feed = dict(feed.get("core") or {})
    core_current = current_versions.get(CORE_COMPONENT_ID, {})
    core_available_version = str(core_feed.get("release_version") or "")
    core_status = _build_update_status(
        str(core_current.get("current_version") or ""),
        core_available_version,
        installed=bool(core_current.get("installed")),
    )
    core_summary = {
        "component_id": CORE_COMPONENT_ID,
        "title": str(core_feed.get("title") or CORE_COMPONENT_TITLE),
        "current_version": str(core_current.get("current_version") or ""),
        "available_version": core_available_version,
        "status": core_status,
        "artifact_type": str(core_feed.get("artifact_type") or "installer"),
        "artifact_path": str(core_feed.get("artifact_path") or ""),
        "sha256": str(core_feed.get("sha256") or ""),
        "installed": bool(core_current.get("installed")),
        # OPT-38 incremental-update extras (additive; absent in old feeds):
        "size": int(core_feed.get("size") or 0),
        "required": bool(core_feed.get("required")),
        "min_version": str(core_feed.get("min_version") or ""),
        "release_notes": str(core_feed.get("release_notes") or ""),
        "release_notes_path": str(core_feed.get("release_notes_path") or ""),
        "delta": dict(core_feed["delta"]) if isinstance(core_feed.get("delta"), dict) else None,
    }

    component_summaries: list[dict[str, Any]] = []
    for component in feed.get("components") or []:
        if not isinstance(component, dict):
            continue
        module_id = str(component.get("module_id") or "").strip()
        if not module_id:
            continue
        current = current_versions.get(module_id, {})
        available_version = str(component.get("release_version") or component.get("version") or "").strip()
        installed = bool(current.get("installed"))
        status = _build_update_status(
            str(current.get("current_version") or ""),
            available_version,
            installed=installed,
        )
        if str(component.get("artifact_type") or "") == "core_bundle" and status == "update_available":
            status = "update_with_core"
        if not installed and status == "available":
            status = "not_installed"
        component_summaries.append(
            {
                "component_id": module_id,
                "title": str(component.get("title") or module_id),
                "tier": str(component.get("tier") or ""),
                "delivery": str(component.get("delivery") or ""),
                "current_version": str(current.get("current_version") or ""),
                "available_version": available_version,
                "status": status,
                "artifact_type": str(component.get("artifact_type") or ""),
                "artifact_path": str(component.get("artifact_path") or ""),
                "sha256": str(component.get("sha256") or ""),
                "installed": installed,
            }
        )

    has_updates = core_summary["status"] == "update_available" or any(
        item["status"] in {"update_available", "available", "not_installed"} for item in component_summaries
    )

    return {
        "source": context,
        "core": core_summary,
        "components": component_summaries,
        "has_updates": has_updates,
    }


def set_module_enabled(module_id: str, enabled: bool) -> dict[str, Any]:
    record = _package_record(module_id)
    if enabled and record["tier"] != "basic" and not record["installed"]:
        raise RuntimeError(f"{record['title']} is not installed yet.")
    current = module_package_map()
    patch = {
        "modules": {module_id: bool(enabled)},
        "module_packages": {
            module_id: {
                "status": current.get(module_id, {}).get("status", "installed" if enabled else "not_installed"),
                "requires_restart": True,
            }
        },
    }
    return save_runtime_profile(patch)


def _module_install_logger():
    """Dedicated module-installation log (mirrors the license.log pattern).

    Lines go to ``<User Data>/logs/module_install.log`` AND propagate to the
    normal app log, so field diagnosis of "the installer said it installed X"
    no longer depends on scrollback. Never raises — on any handler failure the
    plain named logger is returned and propagation still records the lines.
    """
    import logging

    logger = logging.getLogger("aipacs.module_install")
    if not getattr(logger, "_aipacs_file_handler_ready", False):
        try:
            log_dir = user_data_root() / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(log_dir / "module_install.log", encoding="utf-8")
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(message)s")
            )
            logger.addHandler(handler)
            if logger.level == logging.NOTSET or logger.level > logging.INFO:
                logger.setLevel(logging.INFO)
        except Exception:
            pass
        logger._aipacs_file_handler_ready = True  # type: ignore[attr-defined]
    return logger


def module_feature_flag_spec(module_id: str) -> dict[str, str] | None:
    """The catalog-declared feature-flag file for a module, or None.

    Shape: ``{"config": "<relative path under the config root>", "key": "enabled"}``.
    """
    spec = module_catalog_map().get(module_id, {}).get("feature_flag")
    if not isinstance(spec, dict):
        return None
    config_rel = str(spec.get("config") or "").strip()
    if not config_rel:
        return None
    key = str(spec.get("key") or "enabled").strip() or "enabled"
    return {"config": config_rel, "key": key}


def module_feature_flag_value(module_id: str) -> bool | None:
    """Read a module's own flag file: True/False when readable, None when unknown.

    Best-effort and config-file-only (an env override the module honours is the
    module's own business); used by dependency validation to say "the Identity
    module is switched off" instead of "module is not installed correctly".
    """
    spec = module_feature_flag_spec(module_id)
    if spec is None:
        return None
    try:
        path = roaming_config_root() / Path(spec["config"])
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8")) or {}
        if isinstance(data, dict) and spec["key"] in data:
            return bool(data[spec["key"]])
    except Exception:
        return None
    return None


def apply_module_feature_flag(module_id: str, enabled: bool) -> bool:
    """Switch a module's own feature-flag config file (never raises).

    Called after a successful, verified install with ``enable_on_install`` —
    installing a module is explicit user intent, so the module must actually
    open afterwards even though the SHIPPED flag template is force-disabled by
    builder/config_sanitizer.py. Only modules that declare ``feature_flag`` in
    MODULE_CATALOG are touched; merges into the existing payload so unknown
    keys survive. Returns True when the flag file now holds the wanted value.
    """
    spec = module_feature_flag_spec(module_id)
    if spec is None:
        return False
    try:
        try:
            seed_user_config_defaults()
        except Exception:
            pass
        path = roaming_config_root() / Path(spec["config"])
        payload: dict[str, Any] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8")) or {}
                if isinstance(data, dict):
                    payload = data
            except Exception:
                payload = {}
        if spec["key"] in payload and bool(payload[spec["key"]]) == bool(enabled):
            return True
        payload[spec["key"]] = bool(enabled)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        _module_install_logger().info(
            "[MODULE_FLAG] module=%s set %s:%s=%s",
            module_id, spec["config"], spec["key"], bool(enabled),
        )
        return True
    except Exception as exc:  # pragma: no cover - disk/permission problems
        _module_install_logger().warning(
            "[MODULE_FLAG] module=%s flag write failed: %s", module_id, exc
        )
        return False


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def module_availability_detail(module_id: str) -> dict[str, Any]:
    """One-call snapshot for "why can't this module open?" diagnostics.

    Read-only; never raises. UIs compose precise dialogs from this instead of
    the banned generic "module is not installed correctly" string.
    """
    try:
        record = _package_record(module_id)
        return {
            "module_id": module_id,
            "title": str(record.get("title") or module_id),
            "tier": str(record.get("tier") or ""),
            "installed": bool(record.get("installed")),
            "enabled": bool(record.get("enabled")),
            "status": str(record.get("status") or ""),
            "warning": str(record.get("warning") or ""),
            "profile_enforced": bool(_should_enforce_module_profile()),
        }
    except Exception:  # pragma: no cover - defensive
        return {
            "module_id": module_id,
            "title": module_id,
            "tier": "",
            "installed": False,
            "enabled": False,
            "status": "",
            "warning": "",
            "profile_enforced": False,
        }


def _normalize_package_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    manifest = dict(payload or {})
    module_id = str(manifest.get("module_id") or "").strip()
    if not module_id:
        raise ValueError("Package manifest does not contain module_id.")
    catalog = module_catalog_map().get(module_id)
    if not catalog:
        raise ValueError(f"Unknown module package '{module_id}'.")
    package_kind = str(manifest.get("package_kind") or catalog.get("package_kind") or "bundled_unlock")
    manifest.setdefault("format_version", MODULE_PACKAGE_FORMAT_VERSION)
    manifest.setdefault("app_name", APP_NAME)
    manifest.setdefault("title", catalog.get("title") or module_id)
    manifest.setdefault("tier", catalog.get("tier") or "optional")
    manifest.setdefault("package_kind", package_kind)
    manifest.setdefault("requires_restart", True)
    manifest.setdefault("payload_dir", MODULE_PACKAGE_PAYLOAD_DIRNAME if package_kind == "runtime_payload" else "")
    manifest.setdefault("python_paths", list(catalog.get("package_python_paths") or []))
    manifest.setdefault("healthcheck_import", str(catalog.get("healthcheck_import") or ""))
    manifest.setdefault("healthcheck_path", str(catalog.get("healthcheck_path") or ""))
    return manifest


def load_module_package_manifest(source: str | Path) -> dict[str, Any]:
    path = Path(source)
    if path.is_dir():
        manifest = _load_module_manifest_file(path / MODULE_PACKAGE_MANIFEST_FILENAME)
        if manifest is None:
            raise FileNotFoundError(f"{MODULE_PACKAGE_MANIFEST_FILENAME} not found in {path}")
        return _normalize_package_manifest(manifest)
    if path.is_file() and path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path, "r") as archive:
            try:
                raw = archive.read(MODULE_PACKAGE_MANIFEST_FILENAME).decode("utf-8")
            except KeyError as exc:
                raise FileNotFoundError(f"{MODULE_PACKAGE_MANIFEST_FILENAME} not found in {path}") from exc
        payload = json.loads(raw) or {}
        if not isinstance(payload, dict):
            raise ValueError("Invalid module package manifest.")
        return _normalize_package_manifest(payload)
    raise FileNotFoundError(f"Unsupported package source: {path}")


def discover_module_packages(folder: str | Path) -> list[dict[str, Any]]:
    root = Path(folder)
    if not root.exists():
        raise FileNotFoundError(str(root))
    packages: list[dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() or child.suffix.lower() == ".zip":
            try:
                manifest = load_module_package_manifest(child)
            except Exception:
                continue
            manifest["source_path"] = str(child)
            packages.append(manifest)
    return packages


def discover_bundled_module_packages() -> list[dict[str, Any]]:
    packages: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in bundled_module_packages_search_roots():
        if not root.exists():
            continue
        for manifest in discover_module_packages(root):
            module_id = str(manifest.get("module_id") or "").strip()
            if not module_id or module_id in seen:
                continue
            seen.add(module_id)
            packages.append(manifest)
    return packages


def _download_module_package(url: str) -> Path:
    downloads_root = module_downloads_root()
    downloads_root.mkdir(parents=True, exist_ok=True)
    suffix = Path(url).suffix or ".zip"
    with tempfile.NamedTemporaryFile(delete=False, dir=downloads_root, suffix=suffix) as handle:
        with urllib.request.urlopen(url, timeout=30) as response:
            shutil.copyfileobj(response, handle)
        return Path(handle.name)


def _extract_module_package(source: Path) -> tuple[dict[str, Any], Path]:
    if source.is_dir():
        return load_module_package_manifest(source), source

    temp_dir = Path(tempfile.mkdtemp(prefix="aipacs_module_pkg_"))
    with zipfile.ZipFile(source, "r") as archive:
        # Zip-slip guard: every member must extract INSIDE temp_dir. A crafted
        # "..\\" or absolute member name in a downloaded package must fail the
        # install, never write outside the extraction root.
        base = temp_dir.resolve()
        for member in archive.namelist():
            target = (temp_dir / member).resolve()
            if target != base and base not in target.parents:
                raise ValueError(f"Unsafe file path inside module package: {member}")
        archive.extractall(temp_dir)
    return load_module_package_manifest(temp_dir), temp_dir


def _write_installed_module_manifest(module_id: str, manifest: dict[str, Any]) -> None:
    path = installed_module_manifest_path(module_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def install_module_package(
    source: str | Path,
    *,
    expected_module_id: str | None = None,
    enable_on_install: bool = True,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Install a module package from a folder, .zip, or http(s) URL.

    The pipeline is the SAME for every channel (installer first-launch
    bootstrap, Settings package/folder/URL, update feed):
    download → hash-verify (when the caller knows the hash) → extract (zip-slip
    guarded) → manifest validate → payload copy → register → profile update →
    runtime activation → VERIFY (dependencies + healthcheck) → feature-flag
    enable. A package whose verification fails is recorded as
    ``install_incomplete`` with the specific reason and its module stays
    disabled — "download finished" is never reported as "installed".
    Every step is logged to <User Data>/logs/module_install.log.
    """
    log = _module_install_logger()
    cleanup_dir: Path | None = None
    cleanup_file: Path | None = None
    materialized_source = Path(source)

    log.info("[MODULE_INSTALL] begin source=%s expected_module=%s", source, expected_module_id or "-")
    if str(source).startswith(("http://", "https://")):
        cleanup_file = _download_module_package(str(source))
        materialized_source = cleanup_file
        try:
            log.info(
                "[MODULE_INSTALL] downloaded url=%s bytes=%s",
                source, materialized_source.stat().st_size,
            )
        except Exception:
            pass

    try:
        if expected_sha256 and materialized_source.is_file():
            actual_sha256 = _file_sha256(materialized_source)
            if actual_sha256.lower() != str(expected_sha256).strip().lower():
                raise ValueError(
                    "Module package hash mismatch for "
                    f"{materialized_source.name}: expected {expected_sha256}, got {actual_sha256}. "
                    "The download may be corrupted or tampered with — not installed."
                )
            log.info("[MODULE_INSTALL] sha256 verified %s", actual_sha256)

        manifest, extracted_root = _extract_module_package(materialized_source)
        cleanup_dir = extracted_root if extracted_root != materialized_source else None
        module_id = str(manifest["module_id"])
        if expected_module_id and expected_module_id != module_id:
            raise ValueError(f"Expected package for '{expected_module_id}', got '{module_id}'.")

        target_dir = module_runtime_dir(module_id)
        payload_dir_name = str(manifest.get("payload_dir") or "").strip()
        package_kind = str(manifest.get("package_kind") or "bundled_unlock")
        if payload_dir_name:
            payload_source = extracted_root / payload_dir_name
            if not payload_source.exists():
                raise FileNotFoundError(f"Package payload directory is missing: {payload_source}")
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            shutil.copytree(payload_source, target_dir, dirs_exist_ok=True)
            (target_dir / MODULE_PACKAGE_MANIFEST_FILENAME).write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        elif package_kind == "runtime_payload":
            raise FileNotFoundError("Runtime payload package does not contain payload files.")

        timestamp = datetime.now(timezone.utc).isoformat()
        installed_from = str(source)
        manifest["installed_from"] = installed_from
        _write_installed_module_manifest(module_id, manifest)
        log.info(
            "[MODULE_INSTALL] registered module=%s version=%s kind=%s payload=%s target=%s",
            module_id, manifest.get("version") or "-", package_kind,
            payload_dir_name or "-", target_dir if target_dir.exists() else "-",
        )
        profile = save_runtime_profile(
            {
                "modules": {module_id: bool(enable_on_install)},
                "module_packages": {
                    module_id: {
                        "status": "installed",
                        "installed_version": str(manifest.get("version") or ""),
                        "installed_from": installed_from,
                        "installed_at_utc": timestamp,
                        "runtime_path": str(target_dir if target_dir.exists() else ""),
                        "archive_name": materialized_source.name,
                        "package_kind": package_kind,
                        "requires_restart": bool(manifest.get("requires_restart", True)),
                        "warning": "",
                    }
                },
            }
        )
        activate_optional_module_runtime(profile)

        # Post-install verification (2026-08-22): dependencies + healthcheck.
        # An install whose module cannot actually load is recorded as
        # install_incomplete WITH the reason and left disabled, instead of
        # being reported "installed successfully" and failing at first click.
        verification = validate_module_installation(module_id)
        if not verification.get("ok"):
            warning = (
                "Installed files failed verification: "
                f"{verification.get('message') or 'unknown reason'}"
            )
            save_runtime_profile(
                {
                    "modules": {module_id: False},
                    "module_packages": {
                        module_id: {
                            "status": "install_incomplete",
                            "warning": warning,
                        }
                    },
                }
            )
            log.error("[MODULE_INSTALL] verification FAILED module=%s: %s", module_id, warning)
            record = _package_record(module_id, manifest=manifest, enabled=False)
            record["warning"] = warning
            return record

        flag_applied = apply_module_feature_flag(module_id, True) if enable_on_install else False
        log.info(
            "[MODULE_INSTALL] verified module=%s healthcheck=ok enabled=%s feature_flag_applied=%s",
            module_id, bool(enable_on_install), flag_applied,
        )
        return _package_record(module_id, manifest=manifest, enabled=bool(enable_on_install))
    except Exception as exc:
        log.error("[MODULE_INSTALL] FAILED source=%s: %s", source, exc)
        raise
    finally:
        if cleanup_dir is not None:
            shutil.rmtree(cleanup_dir, ignore_errors=True)
        if cleanup_file is not None:
            cleanup_file.unlink(missing_ok=True)


def install_component_update(component_id: str, source: str | Path | None = None) -> dict[str, Any]:
    target = str(component_id or "").strip()
    if not target:
        raise ValueError("component_id is required.")
    if target == CORE_COMPONENT_ID:
        raise RuntimeError("Core updates must be prepared with prepare_core_update_installer().")

    context, feed = load_update_feed(source)
    for component in feed.get("components") or []:
        if not isinstance(component, dict):
            continue
        module_id = str(component.get("module_id") or "").strip()
        if module_id != target:
            continue
        artifact_type = str(component.get("artifact_type") or "")
        if artifact_type == "core_bundle":
            raise RuntimeError(f"{component.get('title') or target} is updated through the core installer.")
        artifact_path = str(component.get("artifact_path") or "").strip()
        if not artifact_path:
            raise FileNotFoundError(f"Update artifact path is missing for {target}.")
        resolved_source = resolve_update_artifact_source(artifact_path, context=context)
        # Feed entries carry the package sha256 — enforce it so a truncated or
        # tampered download is rejected instead of installed (2026-08-22).
        return install_module_package(
            resolved_source,
            expected_module_id=target,
            enable_on_install=True,
            expected_sha256=str(component.get("sha256") or "").strip() or None,
        )

    raise FileNotFoundError(f"No update entry was found for {target}.")


def prepare_core_update_installer(source: str | Path | None = None) -> Path:
    context, feed = load_update_feed(source)
    core = dict(feed.get("core") or {})
    artifact_path = str(core.get("artifact_path") or "").strip()
    if not artifact_path:
        raise FileNotFoundError("The update feed does not contain a core installer artifact.")

    resolved_source = resolve_update_artifact_source(artifact_path, context=context)
    parsed = urlparse(resolved_source)
    if parsed.scheme not in {"http", "https"}:
        path = Path(resolved_source)
        if not path.exists():
            raise FileNotFoundError(str(path))
        return path

    target_root = updates_cache_root() / "core"
    target_root.mkdir(parents=True, exist_ok=True)
    filename = Path(parsed.path).name or "AIPacsUpdate.exe"
    target_path = target_root / filename
    with urllib.request.urlopen(resolved_source, timeout=60) as response, target_path.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    return target_path


def launch_core_update_installer(source: str | Path | None = None) -> Path:
    installer_path = prepare_core_update_installer(source)
    if sys.platform == "win32":
        subprocess.Popen(
            [str(installer_path)],
            cwd=str(installer_path.parent),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    return installer_path


def validate_module_installation(module_id: str) -> dict[str, Any]:
    record = _package_record(module_id)
    if not record["installed"] and record["tier"] != "basic":
        return {"ok": False, "message": f"{record['title']} is not installed."}

    # Dependency validation (2026-08-22): catalog ``requires`` entries must be
    # installed, enabled AND — when they declare a feature flag — not switched
    # off. The message NAMES the dependency ("cannot start because ...")
    # instead of the generic "module is not installed correctly".
    for dep_id in [
        str(item).strip()
        for item in (module_catalog_map().get(module_id, {}).get("requires") or [])
        if str(item).strip()
    ]:
        dep = _package_record(dep_id)
        dep_title = str(dep.get("title") or dep_id)
        if dep["tier"] != "basic":
            if not dep["installed"]:
                return {
                    "ok": False,
                    "message": (
                        f"{record['title']} cannot start because the required "
                        f"module '{dep_title}' is not installed."
                    ),
                }
            if not dep["enabled"]:
                return {
                    "ok": False,
                    "message": (
                        f"{record['title']} cannot start because the required "
                        f"module '{dep_title}' is disabled on this workstation."
                    ),
                }
        if module_feature_flag_value(dep_id) is False:
            return {
                "ok": False,
                "message": (
                    f"{record['title']} cannot start because the {dep_title} "
                    "module is switched off in this workstation's settings."
                ),
            }

    healthcheck_import = str(record.get("healthcheck_import") or "")
    if healthcheck_import:
        try:
            __import__(healthcheck_import)
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    healthcheck_path = str(record.get("healthcheck_path") or "")
    if healthcheck_path and record["runtime_path"]:
        candidate = Path(str(record["runtime_path"])) / healthcheck_path
        if not candidate.exists():
            return {"ok": False, "message": f"Missing runtime file: {candidate}"}

    return {"ok": True, "message": f"{record['title']} is ready."}


def sync_runtime_profile_with_catalog() -> list[str]:
    """Materialize NEW catalog module ids into the persisted runtime profile.

    Older installs carry a profile written before a module existed in
    :data:`MODULE_CATALOG` (e.g. ``consultation``/``identity``, added 2026-06-10).
    The in-memory merge (`configured_module_map`) already falls back to catalog
    defaults, but the on-disk file is what the Settings/store UI and support
    diagnostics inspect — so write the missing ids in with their catalog
    defaults. This NEVER changes an id the profile already lists (a customer's
    explicit enable/disable — including a deliberate ``false`` — is preserved),
    and it does NOT auto-enable optional modules (their catalog default is
    ``False``; the commercial gate stays). Never raises.
    """
    import logging as _log

    logger = _log.getLogger(__name__)
    try:
        path = user_runtime_profile_path()
        raw: dict[str, Any] = {}
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8")) or {}
                if isinstance(payload, dict):
                    raw = payload
            except Exception:
                raw = {}
        raw_modules = raw.get("modules") if isinstance(raw.get("modules"), dict) else {}
        raw_packages = (
            raw.get("module_packages")
            if isinstance(raw.get("module_packages"), dict)
            else {}
        )
        missing_modules = [
            module_id for module_id in module_defaults() if module_id not in raw_modules
        ]
        missing_packages = [
            module_id
            for module_id in module_package_defaults()
            if module_id not in raw_packages
        ]
        if not missing_modules and not missing_packages:
            return []
        # An EMPTY patch is deliberate: load_runtime_profile() already merges
        # catalog defaults + the installer-written installation profile, so
        # saving the merged view materializes the missing ids WITHOUT a
        # value-carrying patch that could override installer state (for
        # example a pending "selected_for_install" package status).
        save_runtime_profile({})
        added = sorted(set(missing_modules) | set(missing_packages))
        logger.info(
            "[MODULE_REGISTRY_SYNC] added catalog ids to runtime profile: %s "
            "(defaults only — no existing value changed)",
            added,
        )
        return added
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[MODULE_REGISTRY_SYNC] sync failed (ignored): %s", exc)
        return []


def bootstrap_installer_selected_module_packages(
    profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Install setup-selected bundled packages before optional modules are imported."""
    if not is_frozen():
        return []

    # Make sure modules added to the catalog AFTER this machine's profile was
    # written become visible (with their defaults) before any gating below.
    sync_runtime_profile_with_catalog()

    configured = configured_module_map(profile)
    package_state = module_package_map(profile)
    install_profile = load_installation_profile()
    install_package_state = dict((install_profile.get("module_packages") or {}))

    selected_by_installer: set[str] = set()
    for module_id, state in install_package_state.items():
        state_map = state if isinstance(state, dict) else {}
        status = str(state_map.get("status") or "")
        installed_from = str(state_map.get("installed_from") or "")
        if status == "selected_for_install" or installed_from == "bundled_setup_selection":
            selected_by_installer.add(str(module_id))

    available = {
        str(package.get("module_id") or ""): package
        for package in discover_bundled_module_packages()
        if str(package.get("module_id") or "").strip()
    }
    installed_records: list[dict[str, Any]] = []
    boot_log = _module_install_logger()
    boot_log.info(
        "[MODULE_BOOTSTRAP] installer_selected=%s bundled_available=%s",
        sorted(selected_by_installer) or "-", sorted(available.keys()) or "-",
    )

    def _normalized_python_paths(payload: dict[str, Any] | None) -> list[str]:
        values = (payload or {}).get("python_paths") or []
        return [str(item).strip() for item in values if str(item).strip()]

    for module_id in module_catalog_map().keys():
        enabled = bool(configured.get(module_id, False))
        installer_selected = module_id in selected_by_installer
        if not enabled and not installer_selected:
            continue
        state = package_state.get(module_id)
        package = available.get(module_id)
        record = _package_record(module_id, state=state, enabled=True)
        if record["tier"] == "basic":
            continue

        # Heal stale runtime-payload manifest metadata for installer-selected
        # modules (for example old advanced_mpr manifests with empty
        # python_paths that block import-path activation at startup).
        if record["installed"] and installer_selected and package:
            package_kind = str(package.get("package_kind") or "")
            if package_kind == "runtime_payload":
                installed_manifest = load_installed_module_manifest(module_id) or {}
                bundled_paths = _normalized_python_paths(package)
                installed_paths = _normalized_python_paths(installed_manifest)
                if bundled_paths and installed_paths != bundled_paths:
                    try:
                        installed_records.append(
                            install_module_package(
                                str(package.get("source_path") or ""),
                                expected_module_id=module_id,
                                enable_on_install=True,
                            )
                        )
                    except Exception as exc:
                        save_runtime_profile(
                            {
                                "modules": {module_id: False},
                                "module_packages": {
                                    module_id: {
                                        "status": "install_failed",
                                        "installed_from": str(package.get("source_path") or ""),
                                        "requires_restart": True,
                                        "warning": f"Bundled package refresh failed: {exc}",
                                    }
                                },
                            }
                        )
                    continue

        if record["installed"]:
            continue

        if not package:
            if str((state or {}).get("status") or "") == "selected_for_install" or str(
                (state or {}).get("installed_from") or ""
            ) == "bundled_setup_selection":
                boot_log.error(
                    "[MODULE_BOOTSTRAP] module=%s selected during setup but no "
                    "bundled package files were found under %s",
                    module_id,
                    [str(root) for root in bundled_module_packages_search_roots()],
                )
                save_runtime_profile(
                    {
                        "modules": {module_id: False},
                        "module_packages": {
                            module_id: {
                                "status": "install_failed",
                                "installed_from": "bundled_setup_selection",
                                "requires_restart": True,
                                "warning": "Bundled package was selected during setup but no package files were found.",
                            }
                        },
                    }
                )
            continue

        try:
            installed_records.append(
                install_module_package(
                    str(package.get("source_path") or ""),
                    expected_module_id=module_id,
                    enable_on_install=True,
                )
            )
        except Exception as exc:
            save_runtime_profile(
                {
                    "modules": {module_id: False},
                    "module_packages": {
                        module_id: {
                            "status": "install_failed",
                            "installed_from": str(package.get("source_path") or ""),
                            "requires_restart": True,
                            "warning": f"Bundled package install failed: {exc}",
                        }
                    },
                }
            )
    return installed_records


def build_graphics_runtime_patch(
    profile: dict[str, Any],
    *,
    probed_at: datetime | None = None,
) -> dict[str, Any]:
    """Build the persisted runtime payload for the latest graphics probe."""
    timestamp = probed_at or datetime.now(timezone.utc)
    stamp = timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    software = profile.get("software_rendering") or {}
    return {
        "graphics": {
            "last_detected_gpu": bool(profile.get("detected_gpu", False)),
            "last_probe_backend": str(profile.get("detector") or ""),
            "last_probe_device": str(profile.get("device_name") or ""),
            "last_probe_utc": stamp,
            "last_execution_mode": str(profile.get("execution_mode") or ""),
            "last_software_rendering_status": str(software.get("status") or ""),
            "last_software_rendering_warning": str(profile.get("software_rendering_warning") or ""),
        }
    }


def _append_unique_path(paths: list[Path], candidate: Path | None) -> None:
    if candidate is None:
        return
    try:
        resolved = candidate.resolve()
    except Exception:
        resolved = candidate
    if resolved in paths:
        return
    paths.append(resolved)


def graphics_runtime_search_roots() -> list[Path]:
    roots: list[Path] = []
    candidates = [
        bundle_root(),
        install_root(),
        bundled_config_root(),
        bundle_root() / SOFTWARE_GRAPHICS_RUNTIME_DIRNAME,
        install_root() / SOFTWARE_GRAPHICS_RUNTIME_DIRNAME,
        bundle_root() / "PySide6",
        install_root() / "PySide6",
    ]
    for runtime_root in modules_runtime_search_roots():
        candidates.append(runtime_root)
        candidates.append(runtime_root / SOFTWARE_GRAPHICS_RUNTIME_DIRNAME)

    for candidate in candidates:
        if candidate.exists():
            _append_unique_path(roots, candidate)

    try:
        import PySide6

        pkg_dir = Path(PySide6.__file__).resolve().parent
        for candidate in (pkg_dir, pkg_dir / "Qt", pkg_dir / "Qt" / "bin"):
            if candidate.exists():
                _append_unique_path(roots, candidate)
    except Exception:
        pass

    return roots


def find_runtime_binary(filename: str, *, override_env: str | None = None) -> Path | None:
    override = os.environ.get(override_env or "", "").strip() if override_env else ""
    if override:
        override_path = Path(override)
        if override_path.exists():
            return override_path

    normalized = str(filename or "").strip()
    if not normalized:
        return None

    for root in graphics_runtime_search_roots():
        for candidate in (
            root / normalized,
            root / "PySide6" / normalized,
            root / "Qt" / normalized,
            root / "Qt" / "bin" / normalized,
        ):
            if candidate.exists():
                return candidate
    return None


def detect_software_graphics_support() -> dict[str, Any]:
    qt_opengl = find_runtime_binary("opengl32sw.dll", override_env=QT_SOFTWARE_OPENGL_DLL_ENV)
    vtk_osmesa = find_runtime_binary("osmesa.dll", override_env=VTK_OSMESA_DLL_ENV)
    vtk_pipe_swrast = None
    if vtk_osmesa is not None:
        sibling_pipe = vtk_osmesa.resolve().parent / "pipe_swrast.dll"
        if sibling_pipe.exists():
            vtk_pipe_swrast = sibling_pipe
    if vtk_pipe_swrast is None:
        vtk_pipe_swrast = find_runtime_binary("pipe_swrast.dll")

    missing: list[str] = []
    if qt_opengl is None:
        missing.append("opengl32sw.dll")
    if vtk_osmesa is None:
        missing.append("osmesa.dll")
    if vtk_pipe_swrast is None:
        missing.append("pipe_swrast.dll")

    status = "missing"
    if qt_opengl and vtk_osmesa and vtk_pipe_swrast:
        status = "ready"
    elif qt_opengl or vtk_osmesa or vtk_pipe_swrast:
        status = "partial"

    if status == "ready":
        warning = ""
    elif status == "partial":
        warning = (
            "Software OpenGL is only partially available. "
            f"Missing runtime component(s): {', '.join(missing)}."
        )
    else:
        warning = (
            "Software OpenGL runtime was not found. "
            "VTK software rendering requires opengl32sw.dll, osmesa.dll, and pipe_swrast.dll."
        )

    return {
        "qt_opengl_dll": str(qt_opengl or ""),
        "vtk_osmesa_dll": str(vtk_osmesa or ""),
        "vtk_pipe_swrast_dll": str(vtk_pipe_swrast or ""),
        "qt_ready": bool(qt_opengl),
        "vtk_ready": bool(vtk_osmesa),
        "vtk_pipe_ready": bool(vtk_pipe_swrast),
        "ready": bool(qt_opengl and vtk_osmesa and vtk_pipe_swrast),
        "status": status,
        "missing": missing,
        "warning": warning,
    }


def build_windows_graphics_environment(
    profile: dict[str, Any],
    *,
    frozen: bool | None = None,
) -> dict[str, Any]:
    use_gpu = bool(profile.get("use_gpu", False))
    frozen_runtime = is_frozen() if frozen is None else bool(frozen)
    software = dict(profile.get("software_rendering") or detect_software_graphics_support())

    # ── Windows-on-ARM emulation: software-GL is the DANGEROUS path here ─────
    # ROOT CAUSE (live faulthandler, Snapdragon X Elite, 2026-07-08): the
    # bundled Mesa software renderer (llvmpipe / opengl32sw.dll) executes a SIMD
    # instruction Prism's x64-on-ARM emulator does not support → 0xc000001d
    # ILLEGAL INSTRUCTION at vtk_widget.Initialize(). The machine's HARDWARE
    # OpenGL (D3D12 → Adreno, GL 4.6, proven by GLview) works. So on emulated
    # WoA the safe/software default is INVERTED: we must NOT force the bundled
    # llvmpipe; use the system/desktop OpenGL (→ OpenGLOn12 → D3D12 → Adreno).
    # Escape hatch AIPACS_WOA_FORCE_SOFTWARE_GL=1 restores the legacy software
    # path (e.g. to A/B the crash). Only flips the SOFTWARE branch — an explicit
    # GPU profile is already hardware and untouched.
    woa_emulated = False
    try:
        woa_emulated = is_windows_on_arm_emulated()
    except Exception:
        woa_emulated = False
    _woa_force_sw = str(os.environ.get("AIPACS_WOA_FORCE_SOFTWARE_GL", "")).strip().lower() in (
        "1", "true", "yes", "on",
    )
    woa_hardware = bool(woa_emulated and not use_gpu and not _woa_force_sw)

    env: dict[str, str] = {}
    clear_env = [
        "AIPACS_GRAPHICS_EXECUTION_MODE",
        "ANGLE_DEFAULT_PLATFORM",
        "GALLIUM_DRIVER",
        "LIBGL_ALWAYS_INDIRECT",
        "LIBGL_ALWAYS_SOFTWARE",
        "MESA_GL_VERSION_OVERRIDE",
        "OPTIMUS_PERFORMANCE_MODE",
        "QMLSCENE_DEVICE",
        "QSG_RHI_BACKEND",
        SAFE_VIEWER_BACKEND_ENV,
        "QT_OPENGL",
        "QT_OPENGL_DLL",
        "QT_QUICK_BACKEND",
        "QTWEBENGINE_DISABLE_GPU",
        "QT_XCB_GL_INTEGRATION",
        "SHIM_MCCOMPAT",
        "VTK_DEFAULT_OPENGL_WINDOW",
        "VTK_OPENGL_FORCE_SOFTPIPE",
        "VTK_USE_HARDWARE",
        "__GLX_VENDOR_LIBRARY_NAME",
        "__NV_PRIME_RENDER_OFFLOAD",
    ]
    path_prefixes: list[str] = []

    if use_gpu:
        chromium_flags = [
            "--enable-media-stream",
            "--ignore-gpu-blocklist",
            "--enable-gpu-rasterization",
            "--enable-zero-copy",
            "--use-angle=d3d11",
        ]
        env.update(
            {
                "AIPACS_GRAPHICS_EXECUTION_MODE": GRAPHICS_EXECUTION_GPU,
                "ANGLE_DEFAULT_PLATFORM": "d3d11",
                "OPTIMUS_PERFORMANCE_MODE": "1",
                "QT_OPENGL": "desktop",
                "QT_QUICK_BACKEND": "d3d11",
                "QSG_RHI_BACKEND": "d3d11",
                "SHIM_MCCOMPAT": "0x800000001",
                "VTK_USE_HARDWARE": "1",
                "QTWEBENGINE_CHROMIUM_FLAGS": " ".join(chromium_flags),
                "__NV_PRIME_RENDER_OFFLOAD": "1",
                "__GLX_VENDOR_LIBRARY_NAME": "nvidia",
            }
        )
        warning = ""
        execution_mode = GRAPHICS_EXECUTION_GPU
    elif woa_hardware:
        # Windows-on-ARM, emulated, software profile requested → use the
        # SYSTEM/desktop OpenGL (hardware D3D12→Adreno) instead of the crashing
        # bundled llvmpipe. Do NOT put the Mesa software DLLs on PATH and do NOT
        # force QT_OPENGL=software / VTK softpipe. Chromium keeps GPU disabled
        # (WebEngine stability under emulation is separate from VTK).
        chromium_flags = [
            "--enable-media-stream",
            "--disable-gpu",
            "--in-process-gpu",
            "--disable-gpu-compositing",
            "--disable-features=VizDisplayCompositor,UseSkiaRenderer",
            "--use-angle=d3d11",
        ]
        env.update(
            {
                "AIPACS_GRAPHICS_EXECUTION_MODE": GRAPHICS_EXECUTION_GPU,
                "ANGLE_DEFAULT_PLATFORM": "d3d11",
                "QT_OPENGL": "desktop",
                "QSG_RHI_BACKEND": "d3d11",
                "QTWEBENGINE_CHROMIUM_FLAGS": " ".join(chromium_flags),
                "VTK_USE_HARDWARE": "1",
                # Diagnostic breadcrumb (read by the WoA profile + logs).
                "AIPACS_WOA_GRAPHICS": "hardware_desktop_gl",
            }
        )
        warning = (
            "Windows-on-ARM emulation: using the system hardware OpenGL "
            "(D3D12) instead of the bundled software renderer, which crashes "
            "under emulation. If MPR still fails, update the GPU driver and the "
            "Microsoft OpenCL/OpenGL Compatibility Pack."
        )
        viewer_backend_override = ""
        execution_mode = GRAPHICS_EXECUTION_GPU
    else:
        chromium_flags = [
            "--enable-media-stream",
            "--disable-gpu",
            "--in-process-gpu",
            "--disable-gpu-compositing",
            "--disable-features=VizDisplayCompositor,UseSkiaRenderer",
        ]
        chromium_flags.append("--use-angle=warp" if frozen_runtime else "--use-angle=swiftshader")

        env.update(
            {
                "AIPACS_GRAPHICS_EXECUTION_MODE": GRAPHICS_EXECUTION_SOFTWARE,
                "ANGLE_DEFAULT_PLATFORM": "warp",
                "GALLIUM_DRIVER": "llvmpipe",
                "LIBGL_ALWAYS_INDIRECT": "1",
                "LIBGL_ALWAYS_SOFTWARE": "1",
                "MESA_GL_VERSION_OVERRIDE": "3.3",
                "QMLSCENE_DEVICE": "softwarecontext",
                "QSG_RHI_BACKEND": "software",
                "QT_OPENGL": "software",
                "QT_QUICK_BACKEND": "software",
                "QTWEBENGINE_DISABLE_GPU": "1",
                "QTWEBENGINE_CHROMIUM_FLAGS": " ".join(chromium_flags),
                "QT_XCB_GL_INTEGRATION": "none",
                "VTK_OPENGL_FORCE_SOFTPIPE": "1",
                "VTK_USE_HARDWARE": "0",
            }
        )

        qt_opengl_dll = str(software.get("qt_opengl_dll") or "")
        if qt_opengl_dll:
            path_prefixes.append(str(Path(qt_opengl_dll).resolve().parent))
            env["QT_OPENGL_DLL"] = Path(qt_opengl_dll).stem

        vtk_osmesa_dll = str(software.get("vtk_osmesa_dll") or "")
        if vtk_osmesa_dll:
            path_prefixes.append(str(Path(vtk_osmesa_dll).resolve().parent))
            # NOTE: Do NOT set VTK_DEFAULT_OPENGL_WINDOW here.
            # vtkOSOpenGLRenderWindow is off-screen only; forcing it as the
            # process-wide default causes access-violation crashes when
            # QVTKRenderWindowInteractor tries to render on-screen.
            # The Mesa DLLs on PATH are sufficient for VTK to locate the
            # software OpenGL driver without overriding the window class.

        vtk_pipe_swrast_dll = str(software.get("vtk_pipe_swrast_dll") or "")
        if vtk_pipe_swrast_dll:
            path_prefixes.append(str(Path(vtk_pipe_swrast_dll).resolve().parent))

        warning = str(software.get("warning") or "")
        viewer_backend_override = ""
        if not bool(software.get("ready", False)):
            env[SAFE_VIEWER_BACKEND_ENV] = SAFE_VIEWER_BACKEND_DEFAULT
            viewer_backend_override = SAFE_VIEWER_BACKEND_DEFAULT
            suffix = (
                " Viewer fallback will use the PyDicom CPU backend until the "
                "software OpenGL runtime is available."
            )
            warning = f"{warning}{suffix}".strip()
        execution_mode = GRAPHICS_EXECUTION_SOFTWARE
    if use_gpu:
        viewer_backend_override = ""

    if frozen_runtime:
        for internal_dir in (install_root() / "Engine", install_root() / "engine"):
            if internal_dir.exists():
                path_prefixes.insert(0, str(internal_dir))
                break

    unique_prefixes: list[str] = []
    seen_prefixes = set()
    for prefix in path_prefixes:
        key = prefix.lower()
        if key in seen_prefixes:
            continue
        seen_prefixes.add(key)
        unique_prefixes.append(prefix)

    return {
        "execution_mode": execution_mode,
        "software_rendering": software,
        "warning": warning,
        "viewer_backend_override": viewer_backend_override,
        "env": env,
        "clear_env": clear_env,
        "path_prefixes": unique_prefixes,
    }


# ── A0 (2026-08-23): seed once per (src, dst), not once per caller ────────────
# Five `_config_root()` helpers call seed_user_config_defaults() on EVERY call —
# server_profiles, offline_cloud, Identity/config, cloud_consultation and
# aipacs_chat feature flags — plus three module-import call sites. Reading a
# feature flag therefore re-scans the roaming config directory. The end-user log
# for the 2026-08-23 00:47 hang shows EIGHT [SEED_CONFIG] lines inside one
# second, during patient-tab teardown, each doing a full iterdir() + a stat()
# per file on the GUI thread.
#
# Seeding is create-if-missing and the roots cannot change inside a process, so
# repeating it can never produce a different result — only the same directory
# walk again. Memoise on the resolved (src, dst) pair rather than a bare bool so
# tests that seed into different tmp dirs still exercise a real pass.
# Kill switch AIPACS_SEED_CONFIG_ONCE=0 restores seeding on every call.
_SEED_DONE: set = set()


def seed_config_once_enabled() -> bool:
    """AIPACS_SEED_CONFIG_ONCE default ON; '0'/'false'/'off'/'no' disables."""
    raw = os.getenv("AIPACS_SEED_CONFIG_ONCE", "1").strip().lower()
    return raw not in ("0", "false", "off", "no")


def reset_seed_memo_for_tests() -> None:
    """Test hook: forget which (src, dst) pairs have been seeded."""
    _SEED_DONE.clear()


def seed_user_config_defaults() -> None:
    if not is_frozen():
        return

    src_root = bundled_config_root()
    dst_root = roaming_config_root()

    _seed_key = (str(src_root), str(dst_root))
    _seed_once = seed_config_once_enabled()
    if _seed_once and _seed_key in _SEED_DONE:
        return

    if not src_root.exists():
        import logging as _log
        _log.getLogger(__name__).warning(
            "[SEED_CONFIG] bundled config root missing: %s — skipping seed", src_root
        )
        return

    dst_root.mkdir(parents=True, exist_ok=True)
    skip_names = {INSTALLATION_PROFILE_FILENAME}
    copied, skipped, failed = [], [], []
    for src in src_root.iterdir():
        if not src.is_file() or src.name in skip_names:
            continue
        dst = dst_root / src.name
        try:
            # Do not overwrite existing user config here.
            # In frozen installs, this function runs on every startup, so
            # unconditional overwrite would erase user-selected settings
            # (for example Viewer Mode: Advanced/FAST) each launch.
            if not dst.exists():
                shutil.copy2(src, dst)
                copied.append(src.name)
            else:
                skipped.append(src.name)
        except Exception as _copy_err:
            failed.append((src.name, str(_copy_err)))
    import logging as _log
    _seed_log = _log.getLogger(__name__)
    _seed_log.info(
        "[SEED_CONFIG] dst=%s copied=%s skipped=%s failed=%s",
        dst_root, copied, skipped, failed,
    )
    if failed:
        _seed_log.warning("[SEED_CONFIG] copy failures: %s", failed)

    # Subdirectory seeding + versioned key-level migration (2026-06-11).
    # The loop above only handles TOP-LEVEL files, so config families that live
    # in subdirectories (config/identity/*, config/cloud_consultation/*) were
    # never seeded into the roaming root of frozen installs — which silently
    # disabled Identity + Online Consultation on every installed build.
    # Guarded + memoized: must never raise into startup and runs once per process.
    global _CONFIG_MIGRATION_RAN
    if not _CONFIG_MIGRATION_RAN:
        _CONFIG_MIGRATION_RAN = True
        try:
            _seed_config_subdirectories(src_root, dst_root)
            migrate_user_config_defaults(src_root, dst_root)
        except Exception as _mig_err:  # pragma: no cover - defensive
            _seed_log.warning("[CONFIG_MIGRATE] migration pass failed: %s", _mig_err)

    # Recorded only after a COMPLETE pass, so a run that bailed on a missing
    # bundled root is retried rather than memoised away.
    if _seed_once:
        _SEED_DONE.add(_seed_key)


# ── Versioned user-config migration (frozen installs) ─────────────────────────
# Each seeded config-file family carries a CURRENT_CONFIG_VERSION. Bump a
# family's version whenever its bundled template gains NEW default keys that
# existing installs must receive (key-level merge — user-set values, including
# an explicit "enabled": false, are NEVER overwritten). Applied versions are
# recorded in <roaming config root>/config_migrations.json.

CONFIG_MIGRATIONS_FILENAME = "config_migrations.json"

CONFIG_FAMILY_VERSIONS: dict[str, int] = {
    # v1 (2026-06-11): seed the family + add hub keys (hub_mode,
    # consultation_address) introduced by ADR-0004 to pre-hub installs.
    # v2 (2026-06-12): add the optional "center_id" key (assignment workflow
    # v2 creation-only registry metadata; empty = not sent).
    "cloud_consultation/cloud_consultation.json": 2,
    # v1 (2026-06-11): seed the Identity feature flag file.
    "identity/identity.json": 1,
    # v1 (2026-06-11): aipacs_web pairing config (ADR-0008) — new file that
    # older installs cannot have.
    "identity/aipacs_web.json": 1,
    # v1 (2026-07-17): Agent Gateway (mobile / MCP connectivity) feature-flag +
    # settings file. New file older installs cannot have; seeds default-OFF.
    # v2 (2026-07-17): add "advertise_host" — the address the pairing QR lists
    # first on a multi-homed workstation (VPN/tunnel address for remote access).
    # v3 (2026-07-17): add the outbound-rendezvous keys (relay_ws_url,
    # relay_workstation_secret) + "e2e_encryption" for the zero-knowledge relay.
    "agent_gateway/agent_gateway.json": 3,
    # v1 (2026-08-19): AiPacs Chat — the manager console for the ai-pacs.com
    # consultation chat. New file older installs cannot have; seeds default-OFF.
    # The backend address is NOT here: it is the Identity module's
    # (identity/aipacs_web.json), because the token is the Identity module's and
    # a second copy of the address is a second thing to get wrong.
    "aipacs_chat/aipacs_chat.json": 1,
}

_CONFIG_SEED_SKIP_DIRNAMES = {"secrets", "__pycache__"}
_CONFIG_SEED_SKIP_FILENAMES = {".gitignore"}
_CONFIG_MIGRATION_RAN = False


def _seed_config_subdirectories(src_root: Path, dst_root: Path) -> list[str]:
    """Copy bundled config files in SUBDIRECTORIES that the user does not have yet.

    Create-if-missing only — never overwrites an existing user file. Skips
    secret material (``identity/secrets``) and repo housekeeping files.
    Returns the list of copied relative paths (for logging/tests).
    """
    import logging as _log

    copied: list[str] = []
    for src in sorted(src_root.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(src_root)
        if len(rel.parts) < 2:
            continue  # top-level files are handled by seed_user_config_defaults
        if any(part in _CONFIG_SEED_SKIP_DIRNAMES for part in rel.parts[:-1]):
            continue
        if rel.name in _CONFIG_SEED_SKIP_FILENAMES:
            continue
        dst = dst_root / rel
        if dst.exists():
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied.append(rel.as_posix())
        except Exception as exc:
            _log.getLogger(__name__).warning(
                "[SEED_CONFIG] subdir copy failed for %s: %s", rel.as_posix(), exc
            )
    if copied:
        _log.getLogger(__name__).info("[SEED_CONFIG] subdir copied=%s", copied)
    return copied


def migrate_user_config_defaults(src_root: Path, dst_root: Path) -> list[dict[str, Any]]:
    """Key-level merge of NEW bundled default keys into existing user config files.

    For every family in :data:`CONFIG_FAMILY_VERSIONS` whose recorded version is
    older than the current one:

    * missing user file  -> seeded from the bundled template;
    * existing user file -> top-level keys present in the template but absent in
      the user file are ADDED; existing user values (including an explicit
      ``"enabled": false``) are never changed; unparseable user files are left
      untouched.

    Idempotent: applied versions are persisted in ``config_migrations.json`` in
    ``dst_root``. Never raises (per-family failures are logged and skipped).
    Returns the list of applied actions (for logging/tests).
    """
    import logging as _log

    logger = _log.getLogger(__name__)
    actions: list[dict[str, Any]] = []
    state_path = dst_root / CONFIG_MIGRATIONS_FILENAME
    state: dict[str, Any] = {}
    try:
        if state_path.exists():
            payload = json.loads(state_path.read_text(encoding="utf-8")) or {}
            if isinstance(payload, dict):
                state = payload
    except Exception as exc:
        logger.warning("[CONFIG_MIGRATE] state read failed (%s) — starting fresh", exc)
    families = state.get("families")
    if not isinstance(families, dict):
        families = {}
    state_changed = False

    for rel, current_version in CONFIG_FAMILY_VERSIONS.items():
        try:
            applied = int(families.get(rel, 0) or 0)
        except Exception:
            applied = 0
        if applied >= current_version:
            continue
        src = src_root / Path(rel)
        dst = dst_root / Path(rel)
        if not src.is_file():
            # Template absent from this build — do not record the version so a
            # later build that ships the template still migrates.
            continue
        try:
            defaults = json.loads(src.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("[CONFIG_MIGRATE] template unreadable %s: %s", rel, exc)
            continue
        if not isinstance(defaults, dict):
            continue

        added_keys: list[str] = []
        try:
            if not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                added_keys = sorted(defaults.keys())
            else:
                try:
                    current = json.loads(dst.read_text(encoding="utf-8"))
                except Exception as exc:
                    logger.warning(
                        "[CONFIG_MIGRATE] user file unparseable, leaving untouched %s: %s",
                        rel, exc,
                    )
                    continue
                if not isinstance(current, dict):
                    logger.warning(
                        "[CONFIG_MIGRATE] user file is not a JSON object, leaving untouched %s",
                        rel,
                    )
                    continue
                merged = dict(current)
                for key, value in defaults.items():
                    if key not in merged:
                        merged[key] = value
                        added_keys.append(key)
                if added_keys:
                    dst.write_text(
                        json.dumps(merged, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
        except Exception as exc:
            logger.warning("[CONFIG_MIGRATE] migration failed for %s: %s", rel, exc)
            continue

        families[rel] = current_version
        state_changed = True
        logger.info(
            "[CONFIG_MIGRATE] file=%s added_keys=%s version %s→%s",
            rel, added_keys, applied, current_version,
        )
        actions.append(
            {
                "file": rel,
                "added_keys": added_keys,
                "from_version": applied,
                "to_version": current_version,
            }
        )

    if state_changed:
        try:
            state["families"] = families
            state["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(state, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("[CONFIG_MIGRATE] state write failed: %s", exc)
    return actions


def module_enabled_map(profile: dict[str, Any] | None = None) -> dict[str, bool]:
    if not _should_enforce_module_profile():
        # Installer/build-time feature gating should not hide modules when the
        # workstation is executed directly from the source tree.
        return development_module_defaults()

    return configured_module_map(profile)


def is_module_enabled(module_id: str, profile: dict[str, Any] | None = None) -> bool:
    return bool(module_enabled_map(profile).get(module_id, False))


def _normalize_gpu_entries(raw: Any) -> list[dict[str, str]]:
    if isinstance(raw, dict):
        items = [raw]
    elif isinstance(raw, list):
        items = raw
    else:
        items = []

    normalized: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "name": str(item.get("Name") or item.get("name") or "").strip(),
                "vendor": str(
                    item.get("AdapterCompatibility")
                    or item.get("adapter_compatibility")
                    or item.get("vendor")
                    or ""
                ).strip(),
                "driver": str(item.get("DriverVersion") or item.get("driver") or "").strip(),
                "processor": str(item.get("VideoProcessor") or item.get("processor") or "").strip(),
            }
        )
    return normalized


def probe_gpu_support() -> dict[str, Any]:
    result = {
        "has_gpu": False,
        "devices": [],
        "detector": "",
        "error": "",
    }
    if sys.platform != "win32":
        return result

    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        (
            "$gpus = Get-CimInstance Win32_VideoController | "
            "Select-Object Name,AdapterCompatibility,DriverVersion,VideoProcessor; "
            "$gpus | ConvertTo-Json -Compress"
        ),
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=6,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        result["error"] = str(exc)
        return result

    stdout = (completed.stdout or "").strip()
    if completed.returncode != 0 or not stdout:
        result["error"] = (completed.stderr or stdout or "GPU detection failed").strip()
        return result

    try:
        devices = _normalize_gpu_entries(json.loads(stdout))
    except Exception as exc:
        result["error"] = str(exc)
        return result
    accepted = []
    deny_tokens = (
        "microsoft basic display",
        "basic render",
        "remote display",
        "rdp",
        "citrix",
        "vmware",
        "virtualbox",
        "hyper-v",
    )
    vendor_tokens = (
        "nvidia",
        "amd",
        "radeon",
        "intel",
        "iris",
        "uhd",
        "arc",
        "geforce",
        "quadro",
        "tesla",
        "rtx",
    )

    for device in devices:
        signature = " ".join(
            part.lower()
            for part in (device.get("name"), device.get("vendor"), device.get("processor"))
            if part
        )
        if any(token in signature for token in deny_tokens):
            continue
        if any(token in signature for token in vendor_tokens):
            accepted.append(device)

    result["devices"] = devices
    result["has_gpu"] = bool(accepted)
    result["detector"] = "powershell_cim"
    return result


def resolve_graphics_profile() -> dict[str, Any]:
    profile = load_runtime_profile()
    graphics = profile.get("graphics") or {}
    requested_gpu = bool(graphics.get("user_declared_gpu", False))
    preferred_mode = str(graphics.get("preferred_mode") or "cpu_safe").strip().lower()
    software = detect_software_graphics_support() if sys.platform == "win32" else {
        "qt_opengl_dll": "",
        "vtk_osmesa_dll": "",
        "vtk_pipe_swrast_dll": "",
        "qt_ready": False,
        "vtk_ready": False,
        "vtk_pipe_ready": False,
        "ready": False,
        "status": "missing",
        "missing": [],
        "warning": "",
    }

    probe = {
        "has_gpu": False,
        "devices": [],
        "detector": "",
        "error": "",
    }
    if requested_gpu or preferred_mode in {"prefer_gpu", "gpu"}:
        probe = probe_gpu_support()

    use_gpu = bool(requested_gpu and probe.get("has_gpu"))
    device_name = ""
    devices = probe.get("devices") or []
    if devices:
        device_name = str(devices[0].get("name") or devices[0].get("processor") or "").strip()

    return {
        "requested_gpu": requested_gpu,
        "preferred_mode": preferred_mode,
        "use_gpu": use_gpu,
        "execution_mode": GRAPHICS_EXECUTION_GPU if use_gpu else GRAPHICS_EXECUTION_SOFTWARE,
        "detected_gpu": bool(probe.get("has_gpu", False)),
        "detector": str(probe.get("detector") or ""),
        "device_name": device_name,
        "devices": devices,
        "error": str(probe.get("error") or ""),
        "software_rendering": software,
        "software_rendering_ready": bool(software.get("ready", False)),
        "software_rendering_warning": str(software.get("warning") or ""),
    }
