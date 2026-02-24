from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Iterable


THIS_DIR = Path(__file__).resolve().parent
BUILDER_DIR = THIS_DIR.parent
PROJECT_ROOT = BUILDER_DIR.parent
INVENTORY_DIR = BUILDER_DIR / "inventory"


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
) -> list[tuple[str, str]]:
    src_rel = norm_rel(src_rel)
    src_dir = project_path(src_rel)
    if not src_dir.exists():
        return []
    datas: list[tuple[str, str]] = []
    if src_dir.is_file():
        if not is_excluded(src_rel, extra_excludes):
            dest = norm_rel(dest_rel or str(Path(src_rel).parent))
            datas.append((str(src_dir), dest))
        return datas

    dest_root = norm_rel(dest_rel or src_rel)
    for p in _iter_files_under(src_dir):
        rel = norm_rel(p.relative_to(PROJECT_ROOT))
        if is_excluded(rel, extra_excludes):
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
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return sorted(out)


def common_app_datas() -> list[tuple[str, str]]:
    datas: list[tuple[str, str]] = []
    curated = [
        "Qss",
        "Fonts",
        "json-styles",
        "config",
        "education_assets",
        "PacsClient/components/cd_burner/assets",
        "EchoMind/secretary/catalog",
        "EchoMind/secretary/prompts",
        "EchoMind/secretary/module_map.yaml",
        "PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/startup_script.py",
        "PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/unified_logging.py",
        "PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/branding",
        "PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/docs",
    ]
    for rel in curated:
        datas.extend(collect_tree_datas(rel))
    return dedupe_datas(datas)


def app_a_datas() -> list[tuple[str, str]]:
    # App A includes common UI and Slicer-launch support resources.
    return common_app_datas()


def app_b_datas() -> list[tuple[str, str]]:
    datas: list[tuple[str, str]] = []
    curated = [
        "PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/startup_script.py",
        "PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/unified_logging.py",
        "PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/branding",
        "PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/docs",
        "PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/NewMPR2Slicer/Applications/NewMPR2SlicerApp/Resources",
        "PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/NewMPR2Slicer/Modules/Scripted/Home/Resources",
        "config",  # for optional slicer_config.json lookup if user places it here
    ]
    for rel in curated:
        datas.extend(collect_tree_datas(rel))
    # App B does not need full Qss/Fonts from App A unless launcher UI grows later.
    return dedupe_datas(datas)


def icon_path_app_a() -> str | None:
    p = project_path("Qss/images/favicon.ico")
    return str(p) if p.exists() else None


def icon_path_app_b() -> str | None:
    candidates = [
        "PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/branding/icons/AIPacsAdvancedViewer.ico",
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

