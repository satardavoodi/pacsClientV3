"""
Tests for Phase 5D VTKWidget split into vtk_widget/ package.

Verifies:
  1. All mixin classes exist and are importable
  2. VTKWidget MRO includes all mixins in correct order
  3. All 102 methods are accessible on VTKWidget
  4. Module-level globals (grow_vtk_inplace, etc.) are importable
  5. Backward-compat import paths still work
  6. No method accidentally duplicated or missing
  7. Each mixin file has proper logger setup
  8. No circular imports
"""
import importlib
import sys
import types
import pytest


# ── Fixture: fresh import of vtk_widget package ────────────────────────────
@pytest.fixture(scope="module")
def vtk_widget_pkg():
    return importlib.import_module(
        "PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget"
    )


@pytest.fixture(scope="module")
def VTKWidget_cls(vtk_widget_pkg):
    return vtk_widget_pkg.VTKWidget


# ── 1. Mixin import tests ──────────────────────────────────────────────────
MIXIN_MODULES = [
    ("_vw_scroll", "_VWScrollMixin"),
    ("_vw_series", "_VWSeriesMixin"),
    ("_vw_backend", "_VWBackendMixin"),
    ("_vw_progressive", "_VWProgressiveMixin"),
    ("_vw_render", "_VWRenderMixin"),
    ("_vw_camera", "_VWCameraMixin"),
    ("_vw_interactor", "_VWInteractorMixin"),
    ("_vw_dragdrop", "_VWDragDropMixin"),
    ("_vw_overlay", "_VWOverlayMixin"),
]


@pytest.mark.parametrize("module_name,class_name", MIXIN_MODULES)
def test_mixin_importable(module_name, class_name):
    """Each mixin module imports without error and exports its class."""
    full = f"PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget.{module_name}"
    mod = importlib.import_module(full)
    cls = getattr(mod, class_name)
    assert cls is not None
    assert isinstance(cls, type)


# ── 2. MRO tests ───────────────────────────────────────────────────────────
def test_mro_includes_all_mixins(VTKWidget_cls):
    """VTKWidget MRO contains all 9 mixins."""
    mro_names = [c.__name__ for c in VTKWidget_cls.__mro__]
    expected_mixins = [name for _, name in MIXIN_MODULES]
    for mixin in expected_mixins:
        assert mixin in mro_names, f"{mixin} missing from MRO"


def test_mro_order(VTKWidget_cls):
    """MRO has VTKWidget first, then mixins, then QVTKRenderWindowInteractor."""
    mro_names = [c.__name__ for c in VTKWidget_cls.__mro__]
    assert mro_names[0] == "VTKWidget"
    # All mixins must appear before QVTKRenderWindowInteractor
    qt_idx = mro_names.index("QVTKRenderWindowInteractor")
    for _, mixin_name in MIXIN_MODULES:
        mixin_idx = mro_names.index(mixin_name)
        assert mixin_idx < qt_idx, f"{mixin_name} must appear before QVTKRenderWindowInteractor"


# ── 3. Method accessibility ────────────────────────────────────────────────
ALL_EXPECTED_METHODS = [
    # core
    "__init__", "set_method_change_series_on_drop",
    "set_method_change_container_border", "change_container_border",
    "resizeEvent", "cleanup_widget",
    # scroll
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
    # series
    "start_process_combine_series", "start_process_series",
    "_start_qt_viewer", "_hide_qt_viewer", "reset_image",
    "cleanup_image_viewer", "switch_series", "_get_smart_spinner_message",
    "get_count_of_slices",
    # backend
    "_extract_series_number", "_log_backend_resolution", "_log_gpu_boost_plan",
    "_log_slice_range", "_reset_lazy_metrics", "_mark_lazy_first_frame_if_needed",
    "_log_lazy_metrics_if_due", "_disconnect_lazy_loader_signals",
    "_connect_lazy_loader_signals", "_release_bound_lazy_loader",
    "_schedule_force_vtk_reload", "_on_lazy_decode_failed",
    "_on_lazy_slice_ready", "_bind_backend_from_metadata",
    "_ensure_lazy_slice_loaded", "_update_backend_badge",
    # progressive
    "enter_progressive_mode", "exit_progressive_mode",
    "update_available_slice_count", "grow_progressive_series",
    "_is_slice_available", "_show_download_overlay", "_hide_download_overlay",
    "grow_current_series_inplace",
    # render
    "_schedule_render", "_do_render", "_freeze_render_window",
    # camera
    "_capture_camera_state", "_restore_camera_state",
    "_schedule_camera_restore", "save_status_camera",
    # interactor
    "_get_active_style", "_force_release_pointer_states",
    "mouseMoveEvent", "mouseReleaseEvent", "leaveEvent",
    "set_new_interactorstyle", "restore_default_interactorstyle",
    "_ensure_interactor_style_enabled", "set_widgets_on_new_interactorstyle",
    "get_sync_viewer_id", "enable_sync_point", "disable_sync_point",
    "_set_target_cursor", "_create_sync_interactor_style",
    "_on_sync_left_press", "_on_sync_mouse_move", "_on_sync_left_release",
    "_apply_sync_point", "apply_sync_point_from_manager",
    # dragdrop
    "_is_supported_drop_payload", "_is_internal_series_drop_payload",
    "_extract_dropped_series_number", "_arm_drop_target", "_drag_event_point",
    "_restart_drop_dwell", "_reset_drop_hover_state",
    "dragEnterEvent", "dragMoveEvent", "dragLeaveEvent",
    "_show_drop_highlight", "dropEvent",
    # overlay
    "overlay", "clear_overlay", "_update_overlay_extent",
]


@pytest.mark.parametrize("method_name", ALL_EXPECTED_METHODS)
def test_method_accessible(VTKWidget_cls, method_name):
    """Every method from the original widget_viewer.py is accessible on VTKWidget."""
    assert hasattr(VTKWidget_cls, method_name), f"Method {method_name} not found on VTKWidget"


def test_total_method_count(VTKWidget_cls):
    """VTKWidget has at least 102 methods (original count)."""
    # Count methods defined on VTKWidget itself (not inherited from Qt)
    own_methods = set()
    for cls in VTKWidget_cls.__mro__:
        if cls.__name__ in ("QVTKRenderWindowInteractor", "QWidget", "QObject",
                            "QPaintDevice", "Object", "object"):
            break
        for name in cls.__dict__:
            if callable(getattr(cls, name, None)) or isinstance(cls.__dict__[name], (staticmethod, classmethod)):
                own_methods.add(name)
    assert len(own_methods) >= 102, f"Expected ≥102 methods, found {len(own_methods)}"


# ── 4. Module-level globals ─────────────────────────────────────────────────
def test_grow_vtk_inplace_importable(vtk_widget_pkg):
    """grow_vtk_inplace is importable from vtk_widget package."""
    assert hasattr(vtk_widget_pkg, "grow_vtk_inplace")
    assert callable(vtk_widget_pkg.grow_vtk_inplace)


def test_register_unregister_subprocess(vtk_widget_pkg):
    """register/unregister_download_subprocess are importable."""
    assert callable(vtk_widget_pkg.register_download_subprocess)
    assert callable(vtk_widget_pkg.unregister_download_subprocess)


def test_create_qt_viewer_bridge(vtk_widget_pkg):
    """_create_qt_viewer_bridge factory is importable."""
    assert callable(vtk_widget_pkg._create_qt_viewer_bridge)


# ── 5. Backward-compat imports ──────────────────────────────────────────────
def test_backward_compat_widget_viewer():
    """Import VTKWidget from widget_viewer.py (the shim) works."""
    from PacsClient.pacs.patient_tab.ui.patient_ui.widget_viewer import VTKWidget
    assert VTKWidget is not None


def test_backward_compat_widget_viewer_grow():
    """Import grow_vtk_inplace from widget_viewer.py works."""
    from PacsClient.pacs.patient_tab.ui.patient_ui.widget_viewer import grow_vtk_inplace
    assert callable(grow_vtk_inplace)


def test_backward_compat_widget_viewer_globals():
    """Module-level constants/functions importable from widget_viewer.py shim."""
    from PacsClient.pacs.patient_tab.ui.patient_ui.widget_viewer import (
        _RENDER_THROTTLE_MS,
        _SPINNER_HIDE_DELAY_MS,
        _SERIES_DROP_MIME,
    )
    assert isinstance(_RENDER_THROTTLE_MS, (int, float))
    assert isinstance(_SPINNER_HIDE_DELAY_MS, (int, float))
    assert isinstance(_SERIES_DROP_MIME, str)


def test_backward_compat_patient_tab_ui():
    """Import VTKWidget from PacsClient.pacs.patient_tab.ui still works."""
    from PacsClient.pacs.patient_tab.ui import VTKWidget
    assert VTKWidget is not None


def test_switch_series_progressive_sync_seeds_available_count():
    """Progressive switch should publish already-loaded slices immediately."""
    mod = importlib.import_module(
        "PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_series"
    )
    calls = []
    class _FakeWidget(mod._VWSeriesMixin):
        _progressive_mode = True
        image_viewer = type("_FakeViewer", (), {
            "get_count_of_slices": lambda self: 20,
        })()
        _lazy_loader = None
        id_vtk_widget = "v1"

        def update_available_slice_count(self, count):
            calls.append(count)

    fake_widget = _FakeWidget()

    mod._VWSeriesMixin._sync_progressive_available_after_switch(fake_widget)

    assert calls == [20]


def test_progressive_sync_uses_raw_loaded_slice_count_over_progressive_total():
    """Sync helper must use raw loaded slices, not widget progressive total."""
    mod = importlib.import_module(
        "PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_series"
    )
    calls = []
    class _FakeWidget(mod._VWSeriesMixin):
        _progressive_mode = True
        image_viewer = type("_FakeViewer", (), {
            "_slice_count": 20,
            "get_count_of_slices": lambda self: 78,
        })()
        _lazy_loader = None
        id_vtk_widget = "v2"

        def update_available_slice_count(self, count):
            calls.append(count)

    fake_widget = _FakeWidget()

    mod._VWSeriesMixin._sync_progressive_available_after_switch(fake_widget)

    assert calls == [20]


def test_start_process_series_qt_syncs_progressive_available_count():
    """Initial Qt series startup should seed progressive availability immediately."""
    mod = importlib.import_module(
        "PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_series"
    )

    class _Spinner:
        def show_loading(self, _msg):
            pass

        def hide_loading(self):
            pass

        spinner = None

    sync_calls = []
    fake_widget = type("_FakeWidget", (), {
        "_active_backend": "pydicom_qt",
        "_lazy_loader": None,
        "viewport_spinner": _Spinner(),
        "_bind_backend_from_metadata": lambda self, metadata, source=None: None,
        "_start_qt_viewer": lambda self, metadata, metadata_fixed: None,
        "_sync_progressive_available_after_switch": lambda self: sync_calls.append("sync"),
        "setUpdatesEnabled": lambda self, enabled: None,
        "save_status_camera": lambda self, image_viewer: None,
        "_dump_scroll_state": lambda self, tag: None,
        "get_count_of_slices": lambda self: 20,
        "image_viewer": object(),
        "height_viewer": 0,
    })()

    metadata = {
        "series": {
            "series_number": "201",
            "series_description": "Test",
            "modality": "CT",
        }
    }
    vtk_image_data = type("_FakeVtk", (), {
        "GetDimensions": lambda self: (512, 512, 20),
    })()

    mod._VWSeriesMixin.start_process_series(
        fake_widget,
        vtk_image_data,
        metadata,
        0,
        0,
        {},
    )

    assert sync_calls == ["sync"]


def test_qt_wheel_fast_path_clamps_to_progressive_available_slices():
    """Qt wheel fast-path must not scroll beyond loaded slices in progressive mode."""
    mod = importlib.import_module(
        "PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_scroll"
    )

    class _FakeImageViewer:
        def __init__(self):
            self._slice = 0
            self.last_index_slice_saved = 0
            self.calls = []

        def GetSlice(self):
            return self._slice

        def set_slice(self, idx, fast_interaction=False, interaction_type=''):
            self._slice = int(idx)
            self.calls.append((int(idx), bool(fast_interaction), interaction_type))

    class _FakeSlider:
        def __init__(self):
            self._value = 0

        def blockSignals(self, _blocked):
            pass

        def setValue(self, value):
            self._value = int(value)

        def value(self):
            return self._value

    class _FakeDelta:
        def __init__(self, y):
            self._y = y

        def y(self):
            return self._y

    class _FakeEvent:
        def __init__(self, y):
            self.accepted = False
            self._delta = _FakeDelta(y)

        def angleDelta(self):
            return self._delta

        def accept(self):
            self.accepted = True

    fake_widget = types.SimpleNamespace(
        _qt_bridge_active=True,
        _active_backend="pydicom_qt",
        _progressive_mode=True,
        _available_slice_count=2,
        image_viewer=_FakeImageViewer(),
        slider=_FakeSlider(),
        _on_slice_changed_cb=None,
        patient_widget=None,
        get_count_of_slices=lambda: 20,
    )
    fake_widget._get_interactive_slice_count = types.MethodType(
        mod._VWScrollMixin._get_interactive_slice_count,
        fake_widget,
    )
    fake_widget.wheelEvent = types.MethodType(mod._VWScrollMixin.wheelEvent, fake_widget)

    fake_widget.wheelEvent(_FakeEvent(-120))
    fake_widget.wheelEvent(_FakeEvent(-120))

    assert fake_widget.image_viewer.calls == [(1, True, 'wheel')]
    assert fake_widget.image_viewer.GetSlice() == 1
    assert fake_widget.slider.value() == 1


# ── 6. No duplicate methods across mixins ───────────────────────────────────
def test_no_duplicate_methods():
    """No method name appears in more than one mixin."""
    seen = {}
    for mod_name, class_name in MIXIN_MODULES:
        full = f"PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget.{mod_name}"
        mod = importlib.import_module(full)
        cls = getattr(mod, class_name)
        for name in cls.__dict__:
            if name.startswith("_") and name.startswith("__") and name.endswith("__"):
                continue  # skip dunder
            if name in seen:
                pytest.fail(
                    f"Method '{name}' duplicated in {seen[name]} and {class_name}"
                )
            seen[name] = class_name


# ── 7. Logger setup ────────────────────────────────────────────────────────
@pytest.mark.parametrize("module_name,class_name", MIXIN_MODULES)
def test_mixin_has_logger(module_name, class_name):
    """Each mixin module has a module-level logger."""
    full = f"PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget.{module_name}"
    mod = importlib.import_module(full)
    assert hasattr(mod, "logger"), f"{module_name} missing logger"
    import logging
    assert isinstance(mod.logger, logging.Logger)


def test_globals_has_logger():
    """_vw_globals module has a logger."""
    from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget import _vw_globals
    assert hasattr(_vw_globals, "logger")


# ── 8. No circular imports ─────────────────────────────────────────────────
def test_no_circular_import():
    """Importing vtk_widget package doesn't raise circular import errors."""
    # Force reimport to catch circular deps
    pkg = "PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget"
    submodules = [
        f"{pkg}.{m}" for m, _ in MIXIN_MODULES
    ] + [f"{pkg}.widget", f"{pkg}._vw_globals"]

    for mod_name in submodules:
        if mod_name in sys.modules:
            del sys.modules[mod_name]

    # This should not raise
    importlib.import_module(pkg)


# ── 9. Runtime name resolution — catches missing imports in method bodies ──
import ast
import pathlib

_VTK_PKG_DIR = pathlib.Path(__file__).resolve().parents[3] / (
    "PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget"
)

# Python builtins + common implicit names that AST reports but aren't imports
_BUILTINS_AND_IMPLICIT = {
    # Python builtins
    "True", "False", "None", "print", "len", "range", "int", "float", "str",
    "bool", "list", "dict", "set", "tuple", "type", "bytes", "bytearray",
    "super", "property", "staticmethod", "classmethod", "isinstance",
    "issubclass", "getattr", "setattr", "hasattr", "delattr", "id", "hex",
    "abs", "min", "max", "sum", "round", "sorted", "reversed", "enumerate",
    "zip", "map", "filter", "any", "all", "next", "iter", "open", "repr",
    "hash", "callable", "ValueError", "TypeError", "KeyError", "IndexError",
    "AttributeError", "RuntimeError", "StopIteration", "FileNotFoundError",
    "OSError", "ImportError", "IOError", "Exception", "BaseException",
    "NotImplementedError", "NameError", "OverflowError", "ZeroDivisionError",
    "MemoryError", "AssertionError",
    # Implicit names from class/function scope
    "self", "cls", "args", "kwargs",
    # Annotations
    "annotations",
}


def _collect_imported_names(tree: ast.Module) -> set[str]:
    """Collect all names made available by import statements at module level."""
    names = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Assign):
            # Module-level assignments (constants)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.FunctionDef):
            # Module-level function defs
            names.add(node.name)
    return names


def _collect_class_level_names(tree: ast.Module) -> set[str]:
    """Collect names defined at class body level (methods, class attrs)."""
    names = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            for item in ast.iter_child_nodes(node):
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(item.name)
                elif isinstance(item, ast.Assign):
                    for t in item.targets:
                        if isinstance(t, ast.Name):
                            names.add(t.id)
    return names


def _collect_referenced_global_names(tree: ast.Module) -> dict[str, list[int]]:
    """
    Walk method bodies and collect Name nodes that reference module-level
    or class-level symbols (not local variables).
    Returns {name: [line_numbers]}.
    """
    refs: dict[str, list[int]] = {}

    for class_node in ast.iter_child_nodes(tree):
        if not isinstance(class_node, ast.ClassDef):
            continue
        for method in ast.iter_child_nodes(class_node):
            if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # Collect local names in this method (params, assignments, for targets, etc.)
            local_names = set()
            for arg in method.args.args + method.args.posonlyargs + method.args.kwonlyargs:
                local_names.add(arg.arg)
            if method.args.vararg:
                local_names.add(method.args.vararg.arg)
            if method.args.kwarg:
                local_names.add(method.args.kwarg.arg)

            for stmt in ast.walk(method):
                if isinstance(stmt, ast.Assign):
                    for t in stmt.targets:
                        if isinstance(t, ast.Name):
                            local_names.add(t.id)
                        elif isinstance(t, ast.Tuple):
                            for e in t.elts:
                                if isinstance(e, ast.Name):
                                    local_names.add(e.id)
                elif isinstance(stmt, ast.For):
                    if isinstance(stmt.target, ast.Name):
                        local_names.add(stmt.target.id)
                    elif isinstance(stmt.target, ast.Tuple):
                        for e in stmt.target.elts:
                            if isinstance(e, ast.Name):
                                local_names.add(e.id)
                elif isinstance(stmt, (ast.With, ast.AsyncWith)):
                    for item in stmt.items:
                        if item.optional_vars and isinstance(item.optional_vars, ast.Name):
                            local_names.add(item.optional_vars.id)
                elif isinstance(stmt, ast.ExceptHandler):
                    if stmt.name:
                        local_names.add(stmt.name)
                elif isinstance(stmt, ast.NamedExpr):
                    if isinstance(stmt.target, ast.Name):
                        local_names.add(stmt.target.id)
                elif isinstance(stmt, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
                    for gen in stmt.generators:
                        if isinstance(gen.target, ast.Name):
                            local_names.add(gen.target.id)
                        elif isinstance(gen.target, ast.Tuple):
                            for e in gen.target.elts:
                                if isinstance(e, ast.Name):
                                    local_names.add(e.id)
                elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # nested function: treat its name as local
                    local_names.add(stmt.name)
                elif isinstance(stmt, ast.ClassDef):
                    # nested class: treat its name as local
                    local_names.add(stmt.name)
                elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
                    # inline imports inside methods
                    if isinstance(stmt, ast.Import):
                        for alias in stmt.names:
                            local_names.add(alias.asname or alias.name.split(".")[0])
                    else:
                        for alias in stmt.names:
                            local_names.add(alias.asname or alias.name)

            # Now find Name references that are NOT local, NOT builtins, NOT self.X
            for node in ast.walk(method):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    name = node.id
                    if name in local_names:
                        continue
                    if name in _BUILTINS_AND_IMPLICIT:
                        continue
                    refs.setdefault(name, []).append(node.lineno)
    return refs


_MIXIN_FILES = sorted(_VTK_PKG_DIR.glob("_vw_*.py"))


@pytest.mark.parametrize(
    "mixin_path",
    _MIXIN_FILES,
    ids=[p.stem for p in sorted(_VTK_PKG_DIR.glob("_vw_*.py"))],
)
def test_mixin_method_names_resolve(mixin_path):
    """
    AST-based test: every non-local Name referenced inside mixin methods
    must be available from module-level imports, class-level defs, or builtins.

    This catches the class of bug where the split script forgets to include
    an import that was present in the original monolithic file.
    """
    source = mixin_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(mixin_path))

    available = (
        _collect_imported_names(tree)
        | _collect_class_level_names(tree)
        | _BUILTINS_AND_IMPLICIT
    )

    referenced = _collect_referenced_global_names(tree)

    missing = {}
    for name, lines in referenced.items():
        if name not in available:
            missing[name] = lines

    if missing:
        details = "; ".join(
            f"{name} (L{','.join(str(l) for l in lines[:3])})"
            for name, lines in sorted(missing.items())
        )
        pytest.fail(
            f"{mixin_path.name} has unresolved names: {details}"
        )
