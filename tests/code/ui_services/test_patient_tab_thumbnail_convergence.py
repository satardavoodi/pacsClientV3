"""Patient-tab thumbnail convergence guards; no live DB, PACS, or images."""

import ast
import asyncio
import base64
import logging
from pathlib import Path
from types import MethodType, SimpleNamespace

from PySide6.QtCore import Qt, Slot
from PacsClient.utils.series_identity import get_series_uid


ROOT = Path(__file__).resolve().parents[3]
THUMBNAILS = (
    ROOT
    / "PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_thumbnails.py"
)
WIDGET = (
    ROOT
    / "PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/widget.py"
)
HOME_OPEN = (
    ROOT / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py"
)


def _method(path: Path, name: str, **namespace):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    node = next(
        item
        for item in ast.walk(tree)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
    )
    scope = dict(namespace)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), scope)
    return scope[name]


def _owner():
    from PacsClient.utils.series_identity import (
        get_series_number,
        get_series_uid,
    )

    events = []
    owner = SimpleNamespace(
        study_uid="synthetic-study",
        import_folder_path="synthetic-path",
        patient_id="synthetic-patient",
        logger=logging.getLogger(__name__),
        _local_thumbnail_workflow=lambda: False,
        has_first_series_displayed=lambda: False,
        _log_open_thumbnail_trace=lambda phase, **fields: events.append((phase, fields)),
    )
    owner._reconcile_server_thumbnail_entries = MethodType(
        _method(
            THUMBNAILS,
            "_reconcile_server_thumbnail_entries",
            Path=Path,
            _get_series_number=get_series_number,
            _get_series_uid=get_series_uid,
        ),
        owner,
    )
    return owner, events


def test_cold_cache_catalog_bootstrap_bypasses_cosmetic_throttle(monkeypatch):
    """The essential series catalog must not wait for first-image visibility."""
    import modules.viewer.fast.ui_throttle as throttle
    import modules.network.socket_client as socket_client
    import modules.network.socket_config as socket_config

    socket_calls = []
    throttle_calls = []
    queued = []

    class FakeClient:
        def __init__(self, *, host, port):
            socket_calls.append((host, port))

        def get_study_thumbnails(self, study_uid, **kwargs):
            return {
                "study_instance_uid": study_uid,
                "series_thumbnails": [
                    {
                        "series_uid": "synthetic-series",
                        "series_number": "7",
                        "thumbnail_path": "synthetic-thumb.png",
                        "image_count": 3,
                    }
                ],
            }

        def disconnect(self):
            return None

    monkeypatch.setattr(
        throttle,
        "should_defer_noncritical_open_network",
        lambda **kwargs: throttle_calls.append(kwargs) or True,
    )
    monkeypatch.setattr(socket_client, "PatientListSocketClient", FakeClient)
    monkeypatch.setattr(
        socket_config,
        "get_socket_server_settings",
        lambda: {"host": "synthetic-host", "port": 50052},
    )

    qmeta = SimpleNamespace(
        invokeMethod=lambda _owner, method_name, _connection: queued.append(method_name)
    )
    load = _method(
        THUMBNAILS,
        "_load_server_thumbnails_async",
        asyncio=asyncio,
        base64=base64,
        check_and_get_thumbnails=lambda *_: [],
        QMetaObject=qmeta,
        Qt=Qt,
        _get_series_uid=get_series_uid,
    )
    owner, events = _owner()

    asyncio.run(load(owner))

    assert throttle_calls == []
    assert socket_calls == [("synthetic-host", 50052)]
    assert queued == ["_render_thumbnails_from_entries_slot"], events
    assert owner._pending_thumbnails_entries[0]["series_uid"] == "synthetic-series"
    assert not any(phase == "patient_tab_thumb_deferred" for phase, _ in events)


def test_first_series_visibility_uses_viewer_controller_as_authority():
    has_first_series_displayed = _method(WIDGET, "has_first_series_displayed")
    owner = SimpleNamespace(
        _first_series_displayed=False,
        viewer_controller=SimpleNamespace(_first_series_displayed=True),
    )

    assert has_first_series_displayed(owner) is True


def test_home_does_not_treat_empty_shell_completion_as_visible_pixels():
    is_visible = _method(HOME_OPEN, "_is_first_series_visible_for_study")
    active_widget = SimpleNamespace(
        study_uid="synthetic-study",
        has_first_series_displayed=lambda: False,
    )
    owner = SimpleNamespace(
        _double_click_first_series_loaded=True,
        _double_click_loading_widget=active_widget,
        _find_widget_by_study_uid=lambda _uid: active_widget,
    )

    assert is_visible(owner, "synthetic-study") is False


def test_empty_shell_loading_complete_does_not_publish_first_image():
    on_loaded = _method(HOME_OPEN, "_on_first_series_loaded")
    events = []
    replays = []
    hide_checks = []
    active_widget = SimpleNamespace(
        study_uid="synthetic-study",
        has_first_series_displayed=lambda: False,
    )
    owner = SimpleNamespace(
        _double_click_first_series_loaded=False,
        _double_click_loading_widget=active_widget,
        _is_first_series_visible_for_study=lambda _uid: False,
        _pending_deferred_counts=lambda _uid: (1, 1, 1),
        _log_open_trace=lambda uid, phase, **fields: events.append(
            (uid, phase, fields)
        ),
        _run_deferred_patient_open_tasks=lambda uid: replays.append(uid),
        _maybe_hide_double_click_loading=lambda: hide_checks.append(True),
    )

    on_loaded(owner)

    assert owner._double_click_first_series_loaded is False
    assert replays == []
    assert not any(phase == "first_series_visible" for _, phase, _ in events)
    assert any(
        phase == "viewer_shell_settled_without_series" for _, phase, _ in events
    )
    assert hide_checks == [True]


def test_partial_cache_renders_the_authoritative_catalog_once(monkeypatch):
    """A cached PNG is media, not permission to omit catalog series without PNGs."""
    import modules.network.socket_client as socket_client
    import modules.network.socket_config as socket_config

    socket_calls = []
    queued = []

    class FakeClient:
        def __init__(self, *, host, port):
            socket_calls.append((host, port))

        def get_study_thumbnails(self, study_uid, **kwargs):
            return {
                "study_instance_uid": study_uid,
                "series_thumbnails": [
                    {
                        "series_uid": "synthetic-series-2",
                        "series_number": "2",
                        "thumbnail_path": "2.png",
                        "image_count": 5,
                    },
                    {
                        "series_uid": "synthetic-series-3",
                        "series_number": "3",
                        "image_count": 7,
                    },
                ],
            }

        def disconnect(self):
            return None

    monkeypatch.setattr(socket_client, "PatientListSocketClient", FakeClient)
    monkeypatch.setattr(
        socket_config,
        "get_socket_server_settings",
        lambda: {"host": "synthetic-host", "port": 50052},
    )
    qmeta = SimpleNamespace(
        invokeMethod=lambda _owner, method_name, _connection: queued.append(method_name)
    )
    load = _method(
        THUMBNAILS,
        "_load_server_thumbnails_async",
        asyncio=asyncio,
        base64=base64,
        check_and_get_thumbnails=lambda *_: [Path("1.png")],
        QMetaObject=qmeta,
        Qt=Qt,
        _get_series_uid=get_series_uid,
    )
    owner, events = _owner()
    owner._server_series_info = {
        str(number): {
            "display_key": str(number),
            "folder_key": str(number),
            "series_number": str(number),
            "series_uid": f"synthetic-series-{number}",
            "study_uid": owner.study_uid,
            "image_count": number,
        }
        for number in (1, 2, 3)
    }
    owner._series_uid_to_number = {
        info["series_uid"]: key for key, info in owner._server_series_info.items()
    }

    asyncio.run(load(owner))

    assert socket_calls == [("synthetic-host", 50052)]
    assert queued == ["_render_thumbnails_from_entries_slot"], events
    entries = owner._pending_thumbnails_entries
    assert [entry["display_key"] for entry in entries] == ["1", "2", "3"]
    assert [entry["file_path"] for entry in entries] == ["1.png", "2.png", ""]
    assert len({entry["series_uid"] for entry in entries}) == 3
    assert any(phase == "patient_tab_thumb_catalog_complete" for phase, _ in events)


def test_complete_cache_uses_one_catalog_render_without_count_rewrite():
    queued = []
    renders = []
    qmeta = SimpleNamespace(
        invokeMethod=lambda _owner, method_name, _connection: queued.append(method_name)
    )
    load = _method(
        THUMBNAILS,
        "_load_server_thumbnails_async",
        asyncio=asyncio,
        base64=base64,
        check_and_get_thumbnails=lambda *_: [Path("1.png"), Path("2.png")],
        QMetaObject=qmeta,
        Qt=Qt,
        _get_series_uid=get_series_uid,
    )
    owner, _events = _owner()
    owner._server_series_info = {
        str(number): {
            "display_key": str(number),
            "folder_key": str(number),
            "series_number": str(number),
            "series_uid": f"synthetic-series-{number}",
            "study_uid": owner.study_uid,
            "image_count": number,
        }
        for number in (1, 2)
    }
    owner._render_thumbnails_from_entries = (
        lambda rows, **kwargs: renders.append((rows, kwargs))
    )

    asyncio.run(load(owner))
    assert queued == ["_render_thumbnails_from_entries_slot"]

    render_slot = _method(THUMBNAILS, "_render_thumbnails_from_entries_slot", Slot=Slot)
    render_slot(owner)

    assert len(renders) == 1
    assert len(renders[0][0]) == 2
    assert renders[0][1] == {"persist_counts": False}
