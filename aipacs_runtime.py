from __future__ import annotations

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
        return Path(sys.executable).resolve().parent
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
        # v2.4.3+: User Data lives next to the executable and engine\ folder,
        # so users can clearly see and access it in Program Files\AIPacs\.
        # The installer creates this directory with users-modify permissions.
        return install_root() / "User Data"
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
        if candidate_str not in sys.path:
            sys.path.insert(0, candidate_str)
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
                    modules_package.__path__.insert(0, str(modules_dir))
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

    record = {
        "module_id": module_id,
        "title": str(catalog.get("title") or package_state.get("title") or module_id),
        "tier": tier,
        "package_kind": package_kind,
        "enabled": bool(configured.get(module_id, False) if enabled is None else enabled),
        "installed": bool(installed),
        "status": "core" if tier == "basic" else ("installed" if installed else "not_installed"),
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


def active_update_source() -> dict[str, Any]:
    payload = load_update_sources()
    active_id = str(payload.get("active_source_id") or "").strip()
    sources = payload.get("sources") or []
    if isinstance(sources, list):
        for source in sources:
            if not isinstance(source, dict):
                continue
            if str(source.get("id") or "").strip() == active_id:
                return dict(source)
        for source in sources:
            if isinstance(source, dict):
                return dict(source)
    return {"id": "", "title": "", "type": "file", "location": "", "channel": "stable"}


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
) -> dict[str, Any]:
    cleanup_dir: Path | None = None
    cleanup_file: Path | None = None
    materialized_source = Path(source)

    if str(source).startswith(("http://", "https://")):
        cleanup_file = _download_module_package(str(source))
        materialized_source = cleanup_file

    try:
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
        return _package_record(module_id, manifest=manifest, enabled=bool(enable_on_install))
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
        return install_module_package(resolved_source, expected_module_id=target, enable_on_install=True)

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


def bootstrap_installer_selected_module_packages(
    profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Install setup-selected bundled packages before optional modules are imported."""
    if not is_frozen():
        return []

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

    for module_id in module_catalog_map().keys():
        enabled = bool(configured.get(module_id, False))
        installer_selected = module_id in selected_by_installer
        if not enabled and not installer_selected:
            continue
        state = package_state.get(module_id)
        record = _package_record(module_id, state=state, enabled=True)
        if record["tier"] == "basic" or record["installed"]:
            continue

        package = available.get(module_id)
        if not package:
            if str((state or {}).get("status") or "") == "selected_for_install" or str(
                (state or {}).get("installed_from") or ""
            ) == "bundled_setup_selection":
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
        internal_dir = install_root() / "engine"
        if internal_dir.exists():
            path_prefixes.insert(0, str(internal_dir))

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


def seed_user_config_defaults() -> None:
    if not is_frozen():
        return

    src_root = bundled_config_root()
    dst_root = roaming_config_root()
    if not src_root.exists():
        import logging as _log
        _log.getLogger(__name__).warning(
            "[SEED_CONFIG] bundled config root missing: %s — skipping seed", src_root
        )
        return

    dst_root.mkdir(parents=True, exist_ok=True)
    skip_names = {INSTALLATION_PROFILE_FILENAME}
    # v2.3.3+ migration: always overwrite viewer_backend_settings.json so that
    # installations that were seeded with the wrong "vtk_simpleitk" default
    # are corrected to "pydicom_qt" on the next app launch.
    force_overwrite_names = {"viewer_backend_settings.json"}
    copied, skipped, failed = [], [], []
    for src in src_root.iterdir():
        if not src.is_file() or src.name in skip_names:
            continue
        dst = dst_root / src.name
        try:
            if not dst.exists() or src.name in force_overwrite_names:
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
