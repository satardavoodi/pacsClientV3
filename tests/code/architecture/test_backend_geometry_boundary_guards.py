"""Architecture guard lint for backend geometry boundary.

Goal:
- Keep VTK/SITK/MPR geometry-sensitive paths explicitly guarded when they are
  not yet migrated to the Advanced geometry contract.
- Keep FAST modules isolated from Advanced geometry contract imports.
- Block shared metadata order mutation patterns in sync/reference helpers.
"""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]

GUARD_TAG = "GEOMETRY_CONTRACT_MISSING_FOR_VTK_PATH"

# P0/high-risk geometry-sensitive insertion points that must remain guarded
# until migrated to SourceGeometry/DisplayGeometry/GeometryAPI adapters.
MANDATORY_GUARD_FILES = [
    "modules/mpr/zeta_mpr/advanced_rendering.py",
    "modules/mpr/zeta_mpr/mpr_viewer/widget.py",
    "modules/mpr/zeta_mpr/mpr_viewer/_mpr_views.py",
    "modules/mpr/zeta_mpr/mpr_viewer/_mpr_crosshair_interact.py",
    "modules/mpr/zeta_mpr/mpr_viewer/_mpr_oblique.py",
    "modules/mpr/curved_mpr/curved_mpr_module.py",
    "modules/mpr/zeta_mpr/CurveMPR/curve_mpr_core.py",
    "modules/mpr/orthogonal/core/volume_loader.py",
    "modules/mpr/orthogonal/core/resampler.py",
]

ADVANCED_CONTRACT_TOKENS = (
    "SourceGeometry",
    "DisplayGeometry",
    "GeometryAPI",
    "modules.viewer.geometry.source_geometry",
    "modules.viewer.geometry.display_geometry",
    "modules.viewer.geometry.geometry_api",
)


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def test_vtk_sitk_mpr_paths_are_guarded_or_contract_bound():
    failures: list[str] = []
    for rel_path in MANDATORY_GUARD_FILES:
        text = _read(rel_path)
        has_guard = GUARD_TAG in text
        has_contract = any(token in text for token in ADVANCED_CONTRACT_TOKENS)
        if not (has_guard or has_contract):
            failures.append(
                f"{rel_path}: missing {GUARD_TAG} and no Advanced geometry contract token found"
            )

    if failures:
        raise AssertionError("\n".join(failures))


def test_fast_modules_do_not_import_advanced_geometry_contract():
    # FAST modules are intentionally isolated from Advanced geometry contract.
    # Approved shared utilities live outside modules/viewer/fast and are not
    # part of this scan.
    fast_dir = REPO_ROOT / "modules" / "viewer" / "fast"
    py_files = sorted(fast_dir.rglob("*.py"))

    forbidden_re = re.compile(
        r"(^|\n)\s*(from\s+modules\.viewer\.geometry\.(source_geometry|display_geometry|geometry_api)\s+import|"
        r"import\s+modules\.viewer\.geometry\.(source_geometry|display_geometry|geometry_api)|"
        r"from\s+modules\.viewer\.geometry\s+import\s+(SourceGeometry|DisplayGeometry|GeometryAPI))",
        re.MULTILINE,
    )

    violations: list[str] = []
    for path in py_files:
        text = path.read_text(encoding="utf-8")
        if forbidden_re.search(text):
            rel = path.relative_to(REPO_ROOT).as_posix()
            violations.append(rel)

    if violations:
        raise AssertionError(
            "FAST modules imported Advanced geometry contract symbols:\n"
            + "\n".join(violations)
        )


def test_shared_sync_paths_do_not_mutate_metadata_instances_order():
    sync_paths = [
        "PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_sync.py",
    ]

    forbidden_patterns = [
        re.compile(r"metadata\[['\"]instances['\"]\]\s*=\s*sorted\("),
        re.compile(r"metadata\[['\"]instances['\"]\]\s*=\s*reference_line\.rl_sort_instances_by_ipp\("),
    ]

    hits: list[str] = []
    for rel_path in sync_paths:
        text = _read(rel_path)
        for pattern in forbidden_patterns:
            if pattern.search(text):
                hits.append(f"{rel_path}: forbidden mutation pattern {pattern.pattern}")

    if hits:
        raise AssertionError("\n".join(hits))
