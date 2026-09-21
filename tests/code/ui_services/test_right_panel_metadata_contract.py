"""Exercise the actual Home card boundary without opening a DB or PACS socket.

Render methods are compiled from production AST with only the Qt/card-construction
edges replaced. The final test uses a real offscreen card to check visible counts.
This does not claim to repair Home's separate ordinal/action-routing defect.
"""
import ast
import copy
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


REPO = Path(__file__).resolve().parents[3]
SOURCE = REPO / "PacsClient/pacs/workstation_ui/home_ui/right_panel_widget.py"


@pytest.fixture
def panel_boundary(monkeypatch):
    names = {"extract_series_info_from_thumbnail", "display_thumbnails_immediately",
             "display_next_thumbnail", "_new_action_thumbnail_manager", "_create_action_thumbnail"}
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    methods = [node for node in ast.walk(tree)
               if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(methods) == len(names)
    namespace = {"_THUMB_BATCHED_RENDER_ENABLED": True, "_THUMB_IMMEDIATE_MAX": 16,
                 "_inside_input_synchronous_dispatch": lambda: False}
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(SOURCE), "exec"), namespace)
    owner_class = type("PanelBoundary", (), {name: namespace[name] for name in names})
    owner = owner_class()
    noop = lambda *args, **kwargs: None
    received = []

    class Manager:
        def __init__(self, callback):
            self.callback = callback
            self._home_series_actions = {}

        def create_thumbnail_widget(self, **kwargs):
            received.append(kwargs)
            return SimpleNamespace(image_button=SimpleNamespace(installEventFilter=noop))

    module = ModuleType("PacsClient.pacs.patient_tab.utils.thumbnail_manager")
    module.ThumbnailManager = Manager
    monkeypatch.setitem(sys.modules, module.__name__, module)
    owner._display_generation = 2
    owner._active_progressive_generation = 2
    owner._cancel_thumbnail_timer = noop
    owner.hide_loading = noop
    owner._set_reserved_content_height = noop
    owner._build_grouped_thumbnail_rows = lambda rows: [
        {"type": "thumbnail", "thumb": row} for row in rows]
    owner._build_pixmap_from_thumb = lambda *args: SimpleNamespace(isNull=lambda: False)
    owner.thumbnailClicked = SimpleNamespace(emit=noop)
    owner.count_label = SimpleNamespace(setText=noop)
    owner.content_widget = SimpleNamespace(setUpdatesEnabled=noop)
    owner.content_grid = SimpleNamespace(addWidget=noop)
    owner.scroll_area = SimpleNamespace(verticalScrollBar=lambda: SimpleNamespace(value=lambda: 0))
    owner._progressive_manager = Manager(noop)
    return owner, received


def _rows():
    base = {"series_number": "02", "_orig_series_number": "02", "modality": "US",
            "series_description": "", "file_path": "synthetic-thumbnail.png"}
    return [
        dict(base, study_uid="study-a", series_uid="still-a", display_key="02",
             folder_key="02", series_path="X:/synthetic/a/02", image_count=25,
             display_image_count=25),
        dict(base, study_uid="study-a", series_uid="cine-a", display_key="900001",
             folder_key="02__cine", series_path="X:/external/a/02__cine", image_count=2,
             display_image_count=420),
        dict(base, study_uid="study-b", series_uid="still-b", display_key="02",
             folder_key="02", series_path="X:/synthetic/b/02", image_count=7,
             display_image_count=7),
    ]


@pytest.mark.parametrize("render", ["immediate", "progressive"])
def test_both_render_paths_preserve_identity_and_object_frame_counts(panel_boundary, render):
    owner, received = panel_boundary
    rows = _rows()
    before = copy.deepcopy(rows)
    if render == "immediate":
        owner.display_thumbnails_immediately(rows, generation=2)
    else:
        owner.thumbnails_to_display = rows
        owner.thumbnail_rows_to_display = owner._build_grouped_thumbnail_rows(rows)
        owner.current_thumbnail_index = 0
        owner.current_displayed_thumbnail_count = 0
        for _ in rows:
            owner.display_next_thumbnail()
    assert len(received) == 3
    fields = ("study_uid", "series_uid", "series_number", "_orig_series_number",
              "display_key", "folder_key", "series_path", "image_count", "display_image_count")
    for source, call in zip(rows, received):
        assert {key: call["series_info"].get(key) for key in fields} == {
            key: source[key] for key in fields}
    assert rows == before


@pytest.mark.parametrize("number", [0, 4, "02", "900002"])
def test_legacy_aliases_defaults_and_number_types_are_unchanged(panel_boundary, number):
    owner, _ = panel_boundary
    result = owner.extract_series_info_from_thumbnail({
        "series_number": number, "Modality": "CT", "description": "Synthetic",
        "ImageCount": 25, "ProtocolName": "Protocol", "body_part": "Region"})
    assert result == {"series_number": number, "modality": "CT",
                      "series_description": "Synthetic", "image_count": 25,
                      "protocol_name": "Protocol", "body_part_examined": "Region"}
    assert type(result["series_number"]) is type(number)
    assert owner.extract_series_info_from_thumbnail({}) == {
        "series_number": 0, "modality": "Unknown", "series_description": "Series 0",
        "image_count": 0, "protocol_name": "", "body_part_examined": ""}


def test_projection_is_detached_and_does_not_copy_pixels_or_patient_fields(panel_boundary):
    owner, _ = panel_boundary
    row = dict(_rows()[1], thumbnail_data=b"synthetic-pixels", patient_name="Synthetic",
               series_instance_uid="cine-a", pixel_instance_count=2)
    result = owner.extract_series_info_from_thumbnail(row)
    assert result.get("series_instance_uid") == "cine-a"
    assert result.get("pixel_instance_count") == 2
    assert "thumbnail_data" not in result and "patient_name" not in result
    result["series_path"] = "changed-result-only"
    assert row["series_path"] == "X:/external/a/02__cine"


def test_real_card_shows_frames_without_replacing_file_count():
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication, QLabel
    from PySide6.QtCore import QCoreApplication, QEvent
    from PacsClient.pacs.patient_tab.utils.thumbnail_manager import ThumbnailManager

    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                  and node.name == "extract_series_info_from_thumbnail")
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(SOURCE), "exec"), namespace)
    info = namespace[method.name](_rows()[1])
    app = QApplication.instance() or QApplication([])
    manager = ThumbnailManager(lambda *args: None)
    pixmap = QPixmap(16, 16)
    pixmap.fill()
    card = manager.create_thumbnail_widget(
        pixmap, label_text="02", thumbnail_index="900001", series_info=info,
        show_progress=False)
    try:
        assert card is not None
        assert "420 images" in [label.text() for label in card.findChildren(QLabel)]
        assert info["image_count"] == 2
        assert card.series_uid == "cine-a"
        # Patient-viewer opaque-key precedence is intentionally untouched.
        assert card.series_number == "900001"
    finally:
        if card is not None:
            card.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
