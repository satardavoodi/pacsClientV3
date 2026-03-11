"""
One-shot import rewriter for the modules/ restructuring.

Walks every .py file in the project and rewrites import paths from
old locations to new modules/ locations.  Handles both ``from X import``
and ``import X`` forms.

Run from project root:
    python tools/_rewrite_imports.py
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ─── Replacement rules ────────────────────────────────────────────────
# Each tuple: (old_pattern_regex, new_string)
# Order matters — more specific patterns first.

RULES: list[tuple[str, str]] = [
    # ── EchoMind ──────────────────────────────────────────────────────
    (r'(?<!modules\.)\bEchoMind\.', 'modules.EchoMind.'),
    (r'\bimport EchoMind\b(?!\.)', 'import modules.EchoMind'),
    (r'\bfrom EchoMind\b', 'from modules.EchoMind'),

    # ── Viewer: VTK (advanced) ────────────────────────────────────────
    (r'\bPacsClient\.pacs\.patient_tab\.viewers\.vtk\.', 'modules.viewer.advanced.'),
    (r'\bPacsClient\.pacs\.patient_tab\.viewers\.vtk\b', 'modules.viewer.advanced'),

    # ── Viewer: PyDicom (fast) ────────────────────────────────────────
    (r'\bPacsClient\.pacs\.patient_tab\.viewers\.pydicom\.', 'modules.viewer.fast.'),
    (r'\bPacsClient\.pacs\.patient_tab\.viewers\.pydicom\b', 'modules.viewer.fast'),

    # ── Viewer: backends shim ─────────────────────────────────────────
    (r'\bPacsClient\.pacs\.patient_tab\.viewers\.backends\.', 'modules.viewer.backends.'),
    (r'\bPacsClient\.pacs\.patient_tab\.viewers\.backends\b', 'modules.viewer.backends'),

    # ── Viewer: root-level viewers package ────────────────────────────
    (r'\bPacsClient\.pacs\.patient_tab\.viewers\.', 'modules.viewer.'),
    (r'\bPacsClient\.pacs\.patient_tab\.viewers\b', 'modules.viewer'),

    # ── Zeta Download Manager ─────────────────────────────────────────
    (r'\bPacsClient\.zeta_download_manager\.', 'modules.download_manager.'),
    (r'\bPacsClient\.zeta_download_manager\b', 'modules.download_manager'),

    # ── Zeta Boost ────────────────────────────────────────────────────
    (r'\bPacsClient\.pacs\.patient_tab\.zeta_boost\.', 'modules.zeta_boost.'),
    (r'\bPacsClient\.pacs\.patient_tab\.zeta_boost\b', 'modules.zeta_boost'),

    # ── Zeta Sync ─────────────────────────────────────────────────────
    (r'\bPacsClient\.pacs\.patient_tab\.zeta_sync\.', 'modules.zeta_sync.'),
    (r'\bPacsClient\.pacs\.patient_tab\.zeta_sync\b', 'modules.zeta_sync'),

    # ── MPR: orthogonal ───────────────────────────────────────────────
    (r'\bPacsClient\.pacs\.patient_tab\.orthogonal_mpr\.', 'modules.mpr.orthogonal.'),
    (r'\bPacsClient\.pacs\.patient_tab\.orthogonal_mpr\b', 'modules.mpr.orthogonal'),

    # ── MPR: advance_mpr_3d_slicer ────────────────────────────────────
    (r'\bPacsClient\.pacs\.patient_tab\.advance_mpr_3d_slicer\.', 'modules.mpr.advanced_3d_slicer.'),
    (r'\bPacsClient\.pacs\.patient_tab\.advance_mpr_3d_slicer\b', 'modules.mpr.advanced_3d_slicer'),

    # ── MPR: zeta_mpr (was "zeta mpr" with space → now proper package) ──
    (r'\bPacsClient\.pacs\.patient_tab\.zeta_mpr\.', 'modules.mpr.zeta_mpr.'),
    (r'\bPacsClient\.pacs\.patient_tab\.zeta_mpr\b', 'modules.mpr.zeta_mpr'),

    # ── Education ─────────────────────────────────────────────────────
    (r'\bPacsClient\.pacs\.education\.', 'modules.education.'),
    (r'\bPacsClient\.pacs\.education\b', 'modules.education'),

    # ── Printing ──────────────────────────────────────────────────────
    (r'(?<!modules\.)\bprinting\.', 'modules.printing.'),
    (r'(?<!modules\.)\bfrom printing\b', 'from modules.printing'),
    (r'(?<!modules\.)\bimport printing\b', 'import modules.printing'),

    # ── Network: socket files ─────────────────────────────────────────
    (r'\bPacsClient\.components\.socket_service\b',               'modules.network.socket_service'),
    (r'\bPacsClient\.components\.socket_client\b',                'modules.network.socket_client'),
    (r'\bPacsClient\.components\.socket_patient_service\b',       'modules.network.socket_patient_service'),
    (r'\bPacsClient\.components\.socket_report_status_service\b', 'modules.network.socket_report_status_service'),
    (r'\bPacsClient\.components\.connection_health_monitor\b',    'modules.network.connection_health_monitor'),
    (r'\bPacsClient\.components\.grpc_client\b',                  'modules.network.grpc_client'),
    (r'\bPacsClient\.components\.dicom_service_pb2_grpc\b',       'modules.network.dicom_service_pb2_grpc'),
    (r'\bPacsClient\.components\.dicom_service_pb2\b',            'modules.network.dicom_service_pb2'),
    (r'\bPacsClient\.components\.dicom_downloader_client_help\b', 'modules.network.dicom_downloader_client_help'),
    (r'\bPacsClient\.components\.dicom_downloader\b',             'modules.network.dicom_downloader'),
    (r'\bPacsClient\.components\.zeta_adapter\b',                 'modules.network.zeta_adapter'),

    # ── Phase 5: Module System ────────────────────────────────────────
    (r'\bPacsClient\.components\.module_manager\b',               'modules.module_system.module_manager'),
    (r'\bPacsClient\.components\.pipeline_orchestrator\b',        'modules.module_system.pipeline_orchestrator'),
    (r'\bPacsClient\.components\.example_modules\b',              'modules.module_system.example_modules'),
    (r'\bPacsClient\.components\.dynamic_thread_optimizer\b',     'modules.module_system.dynamic_thread_optimizer'),

    # ── Phase 5: Network (additional files) ───────────────────────────
    (r'\bPacsClient\.components\.multi\b',                        'modules.network.multi'),
    (r'\bPacsClient\.utils\.socket_config\b',                     'modules.network.socket_config'),
    (r'\bPacsClient\.utils\.socket_token_manager\b',              'modules.network.socket_token_manager'),
    (r'\bPacsClient\.utils\.series_utils\b',                      'modules.network.series_utils'),
    (r'\bPacsClient\.utils\.upload_download_attchments\b',        'modules.network.upload_download_attchments'),
    (r'\bPacsClient\.utils\.upload_task_manager\b',               'modules.network.upload_task_manager'),
    (r'\bPacsClient\.utils\.server_settings_dialog\b',            'modules.network.server_settings_dialog'),

    # ── Phase 5: Viewer (configs + sub-packages) ─────────────────────
    (r'\bPacsClient\.utils\.viewer_backend_config\b',             'modules.viewer.viewer_backend_config'),
    (r'\bPacsClient\.utils\.boost_viewer_config\b',               'modules.viewer.boost_viewer_config'),
    (r'\bPacsClient\.pacs\.patient_tab\.interactor_styles\.',     'modules.viewer.interactor_styles.'),
    (r'\bPacsClient\.pacs\.patient_tab\.interactor_styles\b',     'modules.viewer.interactor_styles'),
    (r'\bPacsClient\.pacs\.patient_tab\.pipeline\.',              'modules.viewer.pipeline.'),
    (r'\bPacsClient\.pacs\.patient_tab\.pipeline\b',              'modules.viewer.pipeline'),
    (r'\bPacsClient\.pacs\.patient_tab\.ui\.widgets\.',           'modules.viewer.widgets.'),
    (r'\bPacsClient\.pacs\.patient_tab\.ui\.widgets\b',           'modules.viewer.widgets'),

    # ── Phase 5: License ──────────────────────────────────────────────
    (r'\bPacsClient\.utils\.license_manager\b',                   'modules.LicenseGenerator.license_manager'),
    (r'\bPacsClient\.utils\.license_dialog\b',                    'modules.LicenseGenerator.license_dialog'),
    (r'\bPacsClient\.utils\.license_generator_gui\b',             'modules.LicenseGenerator.license_generator_gui'),
    (r'\bPacsClient\.utils\.license_generator\b',                 'modules.LicenseGenerator.license_generator'),

    # ── Phase 5: Storage ──────────────────────────────────────────────
    (r'\bPacsClient\.utils\.local_storage_cleanup_manager\b',     'modules.storage.local_storage_cleanup_manager'),
    (r'\bPacsClient\.utils\.patient_cleanup_manager\b',           'modules.storage.patient_cleanup_manager'),
    (r'\bPacsClient\.utils\.storage_calculator\b',                'modules.storage.storage_calculator'),
    (r'\bPacsClient\.utils\.disk_alert_service\b',                'modules.storage.disk_alert_service'),
    (r'\bPacsClient\.utils\.thumbnail_store\b',                   'modules.storage.thumbnail_store'),

    # ── Phase 5: AI Imaging ───────────────────────────────────────────
    (r'\bPacsClient\.pacs\.patient_tab\.ui\.ai_module_ui\.',      'modules.ai_imaging.ai_module_ui.'),
    (r'\bPacsClient\.pacs\.patient_tab\.ui\.ai_module_ui\b',      'modules.ai_imaging.ai_module_ui'),
    (r'\bPacsClient\.pacs\.patient_tab\.ui\.ai_client_ui\.',      'modules.ai_imaging.ai_client_ui.'),
    (r'\bPacsClient\.pacs\.patient_tab\.ui\.ai_client_ui\b',      'modules.ai_imaging.ai_client_ui'),

    # ── Phase 5: Stitching ────────────────────────────────────────────
    (r'\bPacsClient\.pacs\.patient_tab\.stitching\.',             'modules.stitching.'),
    (r'\bPacsClient\.pacs\.patient_tab\.stitching\b',             'modules.stitching'),

    # ── Phase 5: Curved MPR ───────────────────────────────────────────
    (r'\bPacsClient\.pacs\.patient_tab\.curved_mpr_module\b',     'modules.mpr.curved_mpr.curved_mpr_module'),
    (r'\bPacsClient\.pacs\.patient_tab\.curved_mpr_view\b',       'modules.mpr.curved_mpr.curved_mpr_view'),
    (r'\bPacsClient\.pacs\.patient_tab\.curved_mpr_panoramic_view\b', 'modules.mpr.curved_mpr.curved_mpr_panoramic_view'),

    # ── Phase 5: CD Burner ────────────────────────────────────────────
    (r'\bPacsClient\.components\.cd_burner\.',                    'modules.cd_burner.'),
    (r'\bPacsClient\.components\.cd_burner\b',                    'modules.cd_burner'),
]

# Compile all rules once
_COMPILED = [(re.compile(pat), repl) for pat, repl in RULES]

# Directories to skip
SKIP_DIRS = {'.git', '.venv', 'venv', '__pycache__', 'node_modules',
             '.pytest_cache', '.ruff_cache', '.mypy_cache', 'dist', 'build',
             'backups', 'Education', 'education_assets', 'Fonts',
             'attachment', 'Segments', 'source', 'thumbnails',
             'hooks', 'external'}


def should_process(path: Path) -> bool:
    """Return True if this .py file should be processed."""
    parts = set(path.parts)
    if parts & SKIP_DIRS:
        return False
    if path.suffix != '.py':
        return False
    # Skip this script itself
    if path.name == '_rewrite_imports.py':
        return False
    return True


def rewrite_file(path: Path, dry_run: bool = False) -> int:
    """Rewrite imports in a single file.  Returns count of changed lines."""
    try:
        text = path.read_text(encoding='utf-8')
    except (UnicodeDecodeError, PermissionError):
        return 0

    original = text
    for pattern, replacement in _COMPILED:
        text = pattern.sub(replacement, text)

    if text == original:
        return 0

    changes = sum(
        1 for a, b in zip(original.splitlines(), text.splitlines()) if a != b
    )

    if not dry_run:
        path.write_text(text, encoding='utf-8')

    return changes


def main() -> int:
    dry_run = '--dry-run' in sys.argv
    verbose = '--verbose' in sys.argv or '-v' in sys.argv

    total_files = 0
    total_changes = 0

    for dirpath_str, dirnames, filenames in os.walk(str(ROOT)):
        # Prune skip dirs
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        dirpath = Path(dirpath_str)
        for fname in sorted(filenames):
            fpath = dirpath / fname
            if not should_process(fpath):
                continue

            changes = rewrite_file(fpath, dry_run=dry_run)
            if changes > 0:
                rel = fpath.relative_to(ROOT)
                action = "WOULD rewrite" if dry_run else "Rewrote"
                print(f"  {action} {rel}  ({changes} lines)")
                total_files += 1
                total_changes += changes

    mode = "DRY RUN" if dry_run else "APPLIED"
    print(f"\n[{mode}] {total_changes} lines in {total_files} files")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
