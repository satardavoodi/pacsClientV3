#!/usr/bin/env python
"""
Split widget_viewer.py into vtk_widget/ package with mixin classes.

Phase 5D of the VTKWidget refactoring plan.
Creates:
  vtk_widget/
    __init__.py         # re-exports VTKWidget, grow_vtk_inplace, etc.
    widget.py           # VTKWidget core (inherits all mixins), __init__ + small helpers
    _vw_globals.py      # Module-level constants, helper functions, factory funcs
    _vw_scroll.py       # Scroll hot-path: set_slice, wheelEvent, adaptive throttle
    _vw_series.py       # Series management: switch_series, start_process, reset
    _vw_backend.py      # Backend binding: lazy loader, _on_lazy_slice_ready
    _vw_progressive.py  # Progressive display: enter/exit, grow, overlay
    _vw_render.py       # Rendering: schedule_render, do_render, freeze
    _vw_camera.py       # Camera state: capture, restore, schedule_camera_restore
    _vw_interactor.py   # Interactor styles + sync point
    _vw_dragdrop.py     # Drag-and-drop handlers
    _vw_overlay.py      # VTK overlay management

Usage:
    python tools/dev/_split_vtk_widget.py           # execute split
    python tools/dev/_split_vtk_widget.py --dry-run  # preview only
"""

import ast
import os
import sys
import shutil
from pathlib import Path

DRY_RUN = "--dry-run" in sys.argv

BASE = Path(r"C:\AI-Pacs codes\aipacs-pydicom2d")
SRC = BASE / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui" / "widget_viewer.py"
TARGET_DIR = BASE / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui" / "vtk_widget"
OLD_SHIM = BASE / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui" / "vtk_widget.py"

# ── Read source ──────────────────────────────────────────────────────────────
with open(SRC, "r", encoding="utf-8") as f:
    lines = f.readlines()
    source = "".join(lines)

tree = ast.parse(source)

# ── Find VTKWidget class and extract method line ranges ──────────────────────
vtk_class = None
for node in ast.iter_child_nodes(tree):
    if isinstance(node, ast.ClassDef) and node.name == "VTKWidget":
        vtk_class = node
        break

if vtk_class is None:
    print("ERROR: VTKWidget class not found in source")
    sys.exit(1)

# Method name → (start_line_0indexed, end_line_exclusive)
meths = {}
for item in vtk_class.body:
    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
        meths[item.name] = (item.lineno - 1, item.end_lineno)

print(f"Found {len(meths)} methods in VTKWidget (L{vtk_class.lineno}-L{vtk_class.end_lineno})")

# ── Method groupings ─────────────────────────────────────────────────────────
GROUPS = {
    "_vw_scroll": [
        "_reenable_gc", "_restore_reslice_quality", "_should_log_timing",
        "_percentile", "_is_global_download_active_for_probe",
        "_record_scroll_lag_probe", "_estimate_interaction_velocity",
        "_notify_interaction_if_due", "_is_heavy_series_interaction",
        "_effective_fast_render_min_interval_ms", "_effective_fast_skip_velocity_sps",
        "_effective_fast_max_skip_chain", "_quantize_interactive_target",
        "_should_defer_fast_slice_render", "_call_image_viewer_set_slice",
        "queue_interactive_slice_target", "_flush_pending_wheel_slice",
        "_post_scroll_sync_render", "set_slice", "set_slider",
        "wheelEvent", "keyPressEvent",
    ],
    "_vw_series": [
        "start_process_combine_series", "start_process_series",
        "_start_qt_viewer", "_hide_qt_viewer", "reset_image",
        "cleanup_image_viewer", "switch_series", "_get_smart_spinner_message",
        "get_count_of_slices",
    ],
    "_vw_backend": [
        "_extract_series_number", "_log_backend_resolution", "_log_gpu_boost_plan",
        "_log_slice_range", "_reset_lazy_metrics", "_mark_lazy_first_frame_if_needed",
        "_log_lazy_metrics_if_due", "_disconnect_lazy_loader_signals",
        "_connect_lazy_loader_signals", "_release_bound_lazy_loader",
        "_schedule_force_vtk_reload", "_on_lazy_decode_failed",
        "_on_lazy_slice_ready", "_bind_backend_from_metadata",
        "_ensure_lazy_slice_loaded", "_update_backend_badge",
    ],
    "_vw_progressive": [
        "enter_progressive_mode", "exit_progressive_mode",
        "update_available_slice_count", "grow_progressive_series",
        "_is_slice_available", "_show_download_overlay", "_hide_download_overlay",
        "grow_current_series_inplace",
    ],
    "_vw_render": [
        "_schedule_render", "_do_render", "_freeze_render_window",
    ],
    "_vw_camera": [
        "_capture_camera_state", "_restore_camera_state",
        "_schedule_camera_restore", "save_status_camera",
    ],
    "_vw_interactor": [
        "_get_active_style", "_force_release_pointer_states",
        "mouseMoveEvent", "mouseReleaseEvent", "leaveEvent",
        "set_new_interactorstyle", "restore_default_interactorstyle",
        "_ensure_interactor_style_enabled", "set_widgets_on_new_interactorstyle",
        "get_sync_viewer_id", "enable_sync_point", "disable_sync_point",
        "_set_target_cursor", "_create_sync_interactor_style",
        "_on_sync_left_press", "_on_sync_mouse_move", "_on_sync_left_release",
        "_apply_sync_point", "apply_sync_point_from_manager",
    ],
    "_vw_dragdrop": [
        "_is_supported_drop_payload", "_is_internal_series_drop_payload",
        "_extract_dropped_series_number", "_arm_drop_target", "_drag_event_point",
        "_restart_drop_dwell", "_reset_drop_hover_state",
        "dragEnterEvent", "dragMoveEvent", "dragLeaveEvent",
        "_show_drop_highlight", "dropEvent",
    ],
    "_vw_overlay": [
        "overlay", "clear_overlay", "_update_overlay_extent",
    ],
}

CORE_METHODS = [
    "__init__",
    "set_method_change_series_on_drop",
    "set_method_change_container_border",
    "change_container_border",
    "resizeEvent",
    "cleanup_widget",
]

# ── Validate all methods accounted for ───────────────────────────────────────
all_assigned = set(CORE_METHODS)
for group_methods in GROUPS.values():
    all_assigned.update(group_methods)

unassigned = set(meths.keys()) - all_assigned
if unassigned:
    print(f"ERROR: Unassigned methods: {sorted(unassigned)}")
    sys.exit(1)

extra = all_assigned - set(meths.keys())
if extra:
    print(f"ERROR: Methods not found in source: {sorted(extra)}")
    sys.exit(1)

print("All methods accounted for ✓")


# ── Helper: extract method source ────────────────────────────────────────────
def get_method_source(name):
    """Return the source lines for a method, preserving indentation."""
    start, end = meths[name]
    return "".join(lines[start:end])


def get_method_block(method_names):
    """Return combined source for a list of methods, separated by blank lines."""
    parts = []
    for name in method_names:
        parts.append(get_method_source(name))
    return "\n".join(parts)


# ── Import blocks for each mixin ─────────────────────────────────────────────
# Each mixin gets exactly the imports its methods need.

MIXIN_IMPORTS = {
    "_vw_scroll": '''\
"""
Scroll hot-path mixin for VTKWidget.
set_slice, wheelEvent, adaptive throttle, GC suppression, timing probes.
"""
from __future__ import annotations
import gc
import logging
import os
import sys
import time
import threading
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication
from PacsClient.utils.diagnostic_logging import now_ms, log_stage_timing
from modules.viewer.fast.stale_frame_guard import should_render_ready_slice
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_globals import (
    _throttle_background_threads,
    _nt_suspend_download_subprocesses,
    _nt_resume_download_subprocesses,
    _RENDER_THROTTLE_MS,
)

logger = logging.getLogger(__name__)
''',

    "_vw_series": '''\
"""
Series management mixin for VTKWidget.
switch_series, start_process_series, reset_image, cleanup_image_viewer.
"""
from __future__ import annotations
import gc
import logging
import os
import time
import threading
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication
from PacsClient.utils.diagnostic_logging import now_ms, log_stage_timing
from modules.viewer.viewer_backend_config import (
    BACKEND_PYDICOM,
    BACKEND_PYDICOM_QT,
    BACKEND_VTK,
    resolve_viewer_backend,
    load_viewer_backend,
)
from modules.viewer.fast.lazy_volume_registry import (
    acquire_loader,
    release_loader,
)
from modules.viewer.gpu_boost import resolve_gpu_boost_plan
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_globals import (
    _create_qt_viewer_bridge,
    _SPINNER_HIDE_DELAY_MS,
)
import vtkmodules.all as vtk

logger = logging.getLogger(__name__)
''',

    "_vw_backend": '''\
"""
Backend binding and lazy-loader mixin for VTKWidget.
_bind_backend_from_metadata, _on_lazy_slice_ready, lazy loader lifecycle.
"""
from __future__ import annotations
import logging
import time
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QLabel
from PacsClient.utils.diagnostic_logging import now_ms, log_stage_timing
from modules.viewer.viewer_backend_config import (
    BACKEND_PYDICOM,
    BACKEND_PYDICOM_QT,
    BACKEND_VTK,
    load_viewer_backend,
    resolve_viewer_backend,
)
from modules.viewer.gpu_boost import resolve_gpu_boost_plan
from modules.viewer.fast.lazy_volume_registry import (
    acquire_loader,
    release_loader,
)
from modules.viewer.fast.stale_frame_guard import should_render_ready_slice

logger = logging.getLogger(__name__)
''',

    "_vw_progressive": '''\
"""
Progressive display mixin for VTKWidget.
enter/exit progressive mode, grow, download overlay.
"""
from __future__ import annotations
import logging
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

logger = logging.getLogger(__name__)
''',

    "_vw_render": '''\
"""
Rendering mixin for VTKWidget.
schedule_render, do_render, freeze_render_window.
"""
from __future__ import annotations
import logging
import time
from PySide6.QtCore import QTimer
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_globals import (
    _RENDER_THROTTLE_MS,
    _SPINNER_HIDE_DELAY_MS,
)

logger = logging.getLogger(__name__)
''',

    "_vw_camera": '''\
"""
Camera state mixin for VTKWidget.
capture, restore, schedule_camera_restore, save_status_camera.
"""
from __future__ import annotations
import logging
from PySide6.QtCore import QTimer

logger = logging.getLogger(__name__)
''',

    "_vw_interactor": '''\
"""
Interactor style and sync-point mixin for VTKWidget.
set_new_interactorstyle, sync point methods, mouse event overrides.
"""
from __future__ import annotations
import logging
import time
from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication
from modules.viewer.interactor_styles import AbstractInteractorStyle
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_globals import (
    _SYNC_MOVE_THROTTLE_MS,
)
import vtkmodules.all as vtk

logger = logging.getLogger(__name__)
''',

    "_vw_dragdrop": '''\
"""
Drag-and-drop mixin for VTKWidget.
dragEnterEvent, dragMoveEvent, dragLeaveEvent, dropEvent.
"""
from __future__ import annotations
import json
import logging
import time
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_globals import (
    _DROP_HOVER_ARM_MS,
    _DROP_DWELL_MOVE_TOLERANCE_PX,
    _SERIES_DROP_MIME,
)

logger = logging.getLogger(__name__)
''',

    "_vw_overlay": '''\
"""
VTK overlay mixin for VTKWidget.
overlay, clear_overlay, _update_overlay_extent.
"""
from __future__ import annotations
import logging
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap, QColor
import vtkmodules.all as vtk

logger = logging.getLogger(__name__)
''',
}

# ── Mixin class names ────────────────────────────────────────────────────────
MIXIN_CLASSES = {
    "_vw_scroll": "_VWScrollMixin",
    "_vw_series": "_VWSeriesMixin",
    "_vw_backend": "_VWBackendMixin",
    "_vw_progressive": "_VWProgressiveMixin",
    "_vw_render": "_VWRenderMixin",
    "_vw_camera": "_VWCameraMixin",
    "_vw_interactor": "_VWInteractorMixin",
    "_vw_dragdrop": "_VWDragDropMixin",
    "_vw_overlay": "_VWOverlayMixin",
}


def write_file(path, content):
    """Write file (or print if dry-run)."""
    if DRY_RUN:
        line_count = content.count("\n") + 1
        print(f"  [DRY-RUN] Would create {path.name} ({line_count} lines)")
    else:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        line_count = content.count("\n") + 1
        print(f"  Created {path.name} ({line_count} lines)")


# ── Create target directory ──────────────────────────────────────────────────
if not DRY_RUN:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    # Remove old vtk_widget.py shim (replaced by vtk_widget/ package)
    if OLD_SHIM.is_file():
        OLD_SHIM.unlink()
        print(f"Removed old shim: {OLD_SHIM.name}")

# ── 1. Write _vw_globals.py ─────────────────────────────────────────────────
# Contains all module-level code from widget_viewer.py (before VTKWidget class)
module_level_end = vtk_class.lineno - 1  # 1-indexed, so -1 gives 0-indexed end
globals_src = "".join(lines[:module_level_end])
write_file(TARGET_DIR / "_vw_globals.py", globals_src)

# ── 2. Write mixin files ────────────────────────────────────────────────────
for group_name, method_list in GROUPS.items():
    class_name = MIXIN_CLASSES[group_name]
    imports = MIXIN_IMPORTS[group_name]

    body_parts = []
    for mname in method_list:
        body_parts.append(get_method_source(mname))

    body = "\n".join(body_parts)

    content = f"""{imports}

class {class_name}:
    \"\"\"Auto-split mixin — see widget_viewer.py for history.\"\"\"

{body}"""

    write_file(TARGET_DIR / f"{group_name}.py", content)

# ── 3. Write widget.py (core) ───────────────────────────────────────────────
core_imports = '''\
"""
VTKWidget core — assembles all mixins into the final VTKWidget class.

Split from widget_viewer.py during Phase 5D refactoring.
"""
from __future__ import annotations
import os
import logging
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from modules.viewer.interactor_styles import AbstractInteractorStyle
from modules.viewer.widgets import ViewportSpinner
from PacsClient.pacs.patient_tab.ui.patient_ui.viewer_isolation_guard import ViewerIsolationGuard
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QLabel
import vtkmodules.all as vtk
from modules.viewer.viewer_backend_config import (
    BACKEND_VTK,
    load_viewer_backend,
    resolve_viewer_backend,
)
from modules.viewer.gpu_boost import resolve_gpu_boost_plan
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_scroll import _VWScrollMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_series import _VWSeriesMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_backend import _VWBackendMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_progressive import _VWProgressiveMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_render import _VWRenderMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_camera import _VWCameraMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_interactor import _VWInteractorMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_dragdrop import _VWDragDropMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_overlay import _VWOverlayMixin

logger = logging.getLogger(__name__)

'''

# Build core class: inherits all mixins + QVTKRenderWindowInteractor
mixin_bases = [
    "_VWScrollMixin", "_VWSeriesMixin", "_VWBackendMixin",
    "_VWProgressiveMixin", "_VWRenderMixin", "_VWCameraMixin",
    "_VWInteractorMixin", "_VWDragDropMixin", "_VWOverlayMixin",
]
bases_str = ",\n    ".join(mixin_bases + ["QVTKRenderWindowInteractor"])

core_body_parts = []
for mname in CORE_METHODS:
    core_body_parts.append(get_method_source(mname))
core_body = "\n".join(core_body_parts)

core_content = f"""{core_imports}
class VTKWidget(
    {bases_str},
):
    \"\"\"VTK viewer widget — core class with mixin assembly.

    Inherits from 9 mixins for scroll, series, backend, progressive,
    render, camera, interactor, drag-drop, and overlay functionality.
    Only __init__ and minimal helpers remain in this file.
    \"\"\"

{core_body}"""

write_file(TARGET_DIR / "widget.py", core_content)

# ── 4. Write __init__.py ────────────────────────────────────────────────────
init_content = '''\
"""
vtk_widget package — split from widget_viewer.py (Phase 5D).

Public API:
    VTKWidget             — the main viewer widget class
    grow_vtk_inplace      — standalone VTK image grow helper
    register_download_subprocess / unregister_download_subprocess
    _create_qt_viewer_bridge
"""
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget.widget import VTKWidget  # noqa: F401
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_globals import (  # noqa: F401
    grow_vtk_inplace,
    register_download_subprocess,
    unregister_download_subprocess,
    _create_qt_viewer_bridge,
)
'''
write_file(TARGET_DIR / "__init__.py", init_content)

# ── 5. Update widget_viewer.py to be a backward-compat shim ─────────────────
shim_content = '''\
"""Backward-compat shim — actual code is in vtk_widget/ package.

All external imports of ``widget_viewer.VTKWidget`` or
``widget_viewer.grow_vtk_inplace`` continue to work unchanged.
"""
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget import *  # noqa: F401,F403
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget import (  # noqa: F401
    VTKWidget,
    grow_vtk_inplace,
    register_download_subprocess,
    unregister_download_subprocess,
    _create_qt_viewer_bridge,
)
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_globals import (  # noqa: F401
    _throttle_background_threads,
    _nt_suspend_download_subprocesses,
    _nt_resume_download_subprocesses,
    _active_download_pids,
    _RENDER_THROTTLE_MS,
    _SPINNER_HIDE_DELAY_MS,
    _SYNC_MOVE_THROTTLE_MS,
    _DROP_HOVER_ARM_MS,
    _DROP_DWELL_MOVE_TOLERANCE_PX,
    _SERIES_DROP_MIME,
)
'''

if DRY_RUN:
    print(f"  [DRY-RUN] Would overwrite widget_viewer.py as shim")
else:
    # Backup original first
    backup = SRC.with_suffix(".py.bak_phase5d")
    if not backup.exists():
        shutil.copy2(SRC, backup)
        print(f"Backed up original to {backup.name}")
    with open(SRC, "w", encoding="utf-8") as f:
        f.write(shim_content)
    print(f"  Updated widget_viewer.py → backward-compat shim")

# ── Summary ──────────────────────────────────────────────────────────────────
total_mixin_methods = sum(len(v) for v in GROUPS.values())
print(f"\n{'[DRY-RUN] ' if DRY_RUN else ''}Split complete:")
print(f"  {len(GROUPS)} mixin files + widget.py + __init__.py + _vw_globals.py")
print(f"  {total_mixin_methods} methods in mixins, {len(CORE_METHODS)} in core")
print(f"  widget_viewer.py → backward-compat shim")
if OLD_SHIM.is_file() or not DRY_RUN:
    print(f"  vtk_widget.py (old shim) → removed, replaced by vtk_widget/ package")
