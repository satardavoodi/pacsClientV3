from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Iterable

from aipacs_runtime import (
    QT_SOFTWARE_OPENGL_DLL_ENV,
    VTK_OSMESA_DLL_ENV,
    find_runtime_binary,
)


THIS_DIR = Path(__file__).resolve().parent
BUILDER_DIR = THIS_DIR.parent
PROJECT_ROOT = BUILDER_DIR.parent
INVENTORY_DIR = BUILDER_DIR / "inventory"


# ---------------------------------------------------------------------------
# Compressed-DICOM codec plugins  (TS-1, 2026-08-04)
# ---------------------------------------------------------------------------
# pylibjpeg does NOT find its decoder plugins by importing them. It builds its
# decoder table from ``importlib.metadata`` ENTRY POINTS declared in each
# plugin's dist-info. Bundling the modules alone therefore leaves pylibjpeg
# reporting ZERO decoders in a frozen build, and every JPEG / JPEG 2000 /
# JPEG-LS image silently fails to decode — while any import-based capability
# check still reports "all codecs present". Measured on this repo:
#
#     decoders registered (normal):            12
#     decoders registered (metadata stripped):  0
#
# So BOTH the import name AND the distribution metadata must be bundled.
# Keep this the single source of truth; see AIPacs.spec, AIPacs_nuitka.spec.py
# and tools/build/build_lite_viewer.py for the other consumers.
#
# import name -> distribution name
CODEC_PACKAGES: dict[str, str] = {
    "pylibjpeg": "pylibjpeg",
    "libjpeg": "pylibjpeg-libjpeg",     # JPEG baseline/extended/lossless + JPEG-LS
    "openjpeg": "pylibjpeg-openjpeg",   # JPEG 2000 (lossless + lossy) and HTJ2K
    "rle": "pylibjpeg-rle",             # RLE Lossless
}


def codec_hiddenimports() -> list[str]:
    """Import names of the compressed-DICOM codec plugins."""
    return list(CODEC_PACKAGES)


def codec_metadata_datas(copy_metadata) -> list[tuple[str, str]]:
    """``copy_metadata`` results for every codec distribution that is installed.

    ``copy_metadata`` is passed in rather than imported so this module stays
    importable outside a PyInstaller build (tests, tooling).

    A codec missing from the build environment is reported and skipped — never
    fatal — but the release gate is what stops such a build from shipping.
    """
    out: list[tuple[str, str]] = []
    for import_name, dist_name in CODEC_PACKAGES.items():
        try:
            out.extend(copy_metadata(dist_name))
        except Exception as exc:  # not installed in this build environment
            print(f"[spec][codecs] metadata skipped for {dist_name} ({import_name}): {exc}")
    return out


def _load_json(name: str) -> dict:
    path = INVENTORY_DIR / name
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_inventories() -> dict:
    return {
        "entrypoints": _load_json("entrypoints.json"),
        "imports_summary": _load_json("imports_summary.json"),
        "runtime": _load_json("runtime_data_paths_inventory.json"),
        "resources": _load_json("resource_inventory.json"),
    }


def norm_rel(path: str | Path) -> str:
    return str(path).replace("\\", "/").lstrip("./")


def project_path(rel: str) -> Path:
    return (PROJECT_ROOT / rel).resolve()


def _expand_patterns(patterns: Iterable[str]) -> list[str]:
    out: list[str] = []
    for p in patterns:
        p = norm_rel(p)
        if p and p not in out:
            out.append(p)
    return out


def get_privacy_exclude_patterns() -> list[str]:
    runtime = _load_json("runtime_data_paths_inventory.json")
    detected = runtime.get("must_not_package_detected_paths", []) or []
    baseline = runtime.get("must_not_package_patterns", []) or []
    extra = [
        ".venv/**",
        ".venv_build/**",
        "venv/**",
        "builder/**",
        "backups/**",
        "**/__pycache__/**",
        "**/*.pyc",
        "**/*.pyo",
        "**/.git/**",
    ]
    return _expand_patterns([*detected, *baseline, *extra])


def is_excluded(rel_path: str, extra_patterns: Iterable[str] | None = None) -> bool:
    rel_path = norm_rel(rel_path)
    patterns = get_privacy_exclude_patterns()
    if extra_patterns:
        patterns.extend(_expand_patterns(extra_patterns))

    lower_rel = rel_path.lower()
    for pat in patterns:
        pat_norm = norm_rel(pat)
        if not pat_norm:
            continue
        # Directory shorthand (e.g., "generated-files")
        if "/" not in pat_norm and not any(ch in pat_norm for ch in "*?[]"):
            if lower_rel == pat_norm.lower() or lower_rel.startswith(pat_norm.lower() + "/"):
                return True
        # Glob match
        if fnmatch.fnmatchcase(lower_rel, pat_norm.lower()):
            return True
        # If pattern ends with /**, also match directory itself
        if pat_norm.endswith("/**"):
            base = pat_norm[:-3].rstrip("/")
            if lower_rel == base.lower() or lower_rel.startswith(base.lower() + "/"):
                return True
    return False


def _iter_files_under(src_dir: Path) -> Iterable[Path]:
    for p in src_dir.rglob("*"):
        if p.is_file():
            yield p


def collect_tree_datas(
    src_rel: str,
    dest_rel: str | None = None,
    extra_excludes: Iterable[str] | None = None,
    allow_excluded: bool = False,
) -> list[tuple[str, str]]:
    src_rel = norm_rel(src_rel)
    src_dir = project_path(src_rel)
    if not src_dir.exists():
        return []
    datas: list[tuple[str, str]] = []
    if src_dir.is_file():
        if allow_excluded or not is_excluded(src_rel, extra_excludes):
            dest = norm_rel(dest_rel or str(Path(src_rel).parent))
            datas.append((str(src_dir), dest))
        return datas

    dest_root = norm_rel(dest_rel or src_rel)
    for p in _iter_files_under(src_dir):
        rel = norm_rel(p.relative_to(PROJECT_ROOT))
        if not allow_excluded and is_excluded(rel, extra_excludes):
            continue
        subdir = Path(rel).parent
        try:
            suffix_rel = subdir.relative_to(Path(src_rel))
            dest = norm_rel(Path(dest_root) / suffix_rel)
        except Exception:
            dest = dest_root
        datas.append((str(p), dest))
    return datas


def dedupe_datas(datas: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    seen = set()
    out = []
    for src, dest in datas:
        key = (str(Path(src).resolve()).lower(), norm_rel(dest).lower())
        if key in seen:
            continue
        seen.add(key)
        out.append((src, norm_rel(dest)))
    return out


def load_hiddenimports(extra: Iterable[str] | None = None) -> list[str]:
    imports_summary = _load_json("imports_summary.json")
    hidden = list(imports_summary.get("suggested_hiddenimports", []) or [])
    if extra:
        hidden.extend(list(extra))
    # Remove obvious noise and de-dup
    deny = {"logging"}
    out = []
    seen = set()
    for item in hidden:
        if not item or item in deny:
            continue
        if not _keep_runtime_hiddenimport(item):
            continue
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return sorted(out)


def _keep_runtime_hiddenimport(name: str) -> bool:
    deny_fragments = (
        ".tests",
        ".tests.",
        ".conftest",
        ".example_usage",
        ".test_",
        ".seed_",
    )
    deny_suffixes = (
        ".build",
        ".build_nuitka",
    )
    if any(fragment in name for fragment in deny_fragments):
        return False
    if name.endswith(deny_suffixes):
        return False
    return True


def sanitized_config_rel() -> str:
    """SECURITY (2026-07-09) — build-time sanitization of centre-specific config.

    The repo's ``config/`` holds the DEVELOPER centre's real values (PACS host IPs,
    AE titles, reception API URL, EchoMind ``api_key``, Google OAuth
    ``client_secret``), and ``aipacs_runtime.seed_user_config_defaults()`` copies the
    BUNDLED config into every client's roaming config on first run — so packaging
    ``config/`` verbatim seeded the dev centre's configuration (and secrets) into
    every client site.

    Generate a SANITIZED copy (application defaults kept, centre-specific values
    emptied) and return its project-relative path, so the spec packages THAT. The
    developer's own ``config/`` is only READ, never modified (source runs still use
    it — seeding is frozen-only). ABORTS the build if anything would still leak.
    """
    import sys as _sys

    if str(BUILDER_DIR) not in _sys.path:
        _sys.path.insert(0, str(BUILDER_DIR))
    from config_sanitizer import build_clean_config_tree, scan_for_center_values

    rel = "generated-files/build/config_clean"
    out = PROJECT_ROOT / rel
    build_clean_config_tree(PROJECT_ROOT / "config", out)
    leaks = scan_for_center_values(out)
    if leaks:
        raise SystemExit(
            "[spec_utils] ABORT — centre-specific values would be packaged: %r" % (leaks,)
        )
    return rel


def common_app_datas() -> list[tuple[str, str]]:
    datas: list[tuple[str, str]] = []
    # NOTE: "config" is deliberately NOT in this curated list — the sanitized
    # tree is added explicitly below (see sanitized_config_rel).
    curated = [
        "Qss",
        "Fonts",
        "json-styles",
        "education_assets",
        "modules/cd_burner/assets",
        # NOTE: the portable CD viewer (lightViewer_dist) is NOT shipped here.
        # cd_burner is excluded from the engine (appA_workstation.spec
        # optional_prefixes), so it loads only from the run_cd plugin payload
        # — which already carries the viewer. Shipping it in engine datas too
        # was ~97 MB of dead weight in EVERY installer (incl. non-CD users).
        "modules/EchoMind/secretary/catalog",
        "modules/EchoMind/secretary/prompts",
        "modules/EchoMind/secretary/module_map.yaml",
        "modules/mpr/advanced_3d_slicer/slicer_custom_app/startup_script.py",
        "modules/mpr/advanced_3d_slicer/slicer_custom_app/unified_logging.py",
        "modules/mpr/advanced_3d_slicer/slicer_custom_app/branding",
        "modules/mpr/advanced_3d_slicer/slicer_custom_app/docs",
    ]
    for rel in curated:
        datas.extend(collect_tree_datas(rel))
    # Ship the SANITIZED config tree at "config/" (never the developer's config/).
    datas.extend(collect_tree_datas(sanitized_config_rel(), "config", allow_excluded=True))
    return dedupe_datas(datas)


def app_a_datas() -> list[tuple[str, str]]:
    # App A includes common UI and Slicer-launch support resources.
    return common_app_datas()


def app_b_datas() -> list[tuple[str, str]]:
    datas: list[tuple[str, str]] = []
    curated = [
        "modules/mpr/advanced_3d_slicer/slicer_custom_app/startup_script.py",
        "modules/mpr/advanced_3d_slicer/slicer_custom_app/unified_logging.py",
        "modules/mpr/advanced_3d_slicer/slicer_custom_app/branding",
        "modules/mpr/advanced_3d_slicer/slicer_custom_app/docs",
        "modules/mpr/advanced_3d_slicer/slicer_custom_app/NewMPR2Slicer/Applications/NewMPR2SlicerApp/Resources",
        "modules/mpr/advanced_3d_slicer/slicer_custom_app/NewMPR2Slicer/Modules/Scripted/Home/Resources",
        # "config" removed — App B also shipped the developer's raw config/.
    ]
    for rel in curated:
        datas.extend(collect_tree_datas(rel))
    # Sanitized config (for the optional slicer_config.json lookup) — never raw.
    datas.extend(collect_tree_datas(sanitized_config_rel(), "config", allow_excluded=True))
    # App B does not need full Qss/Fonts from App A unless launcher UI grows later.
    return dedupe_datas(datas)


def graphics_runtime_binaries() -> list[tuple[str, str]]:
    binaries: list[tuple[str, str]] = []
    qt_opengl = find_runtime_binary("opengl32sw.dll", override_env=QT_SOFTWARE_OPENGL_DLL_ENV)
    osmesa = find_runtime_binary("osmesa.dll", override_env=VTK_OSMESA_DLL_ENV)
    pipe_swrast = None
    if osmesa is not None:
        sibling_pipe = Path(osmesa).resolve().parent / "pipe_swrast.dll"
        if sibling_pipe.exists():
            pipe_swrast = sibling_pipe
    if pipe_swrast is None:
        pipe_swrast = find_runtime_binary("pipe_swrast.dll")

    for path in (qt_opengl, osmesa, pipe_swrast):
        if path is None:
            continue
        binaries.append((str(path), "."))
    return binaries


def icon_path_app_a() -> str | None:
    p = project_path("Qss/images/favicon.ico")
    return str(p) if p.exists() else None


def icon_path_app_b() -> str | None:
    candidates = [
        "modules/mpr/advanced_3d_slicer/slicer_custom_app/branding/icons/AIPacsAdvancedViewer.ico",
        "Qss/images/favicon.ico",
    ]
    for rel in candidates:
        p = project_path(rel)
        if p.exists():
            return str(p)
    return None


def entrypoint_for(app_key: str, fallback: str) -> str:
    entrypoints = _load_json("entrypoints.json")
    ep = (entrypoints.get(app_key) or {}).get("entrypoint")
    return str(project_path(ep or fallback))

