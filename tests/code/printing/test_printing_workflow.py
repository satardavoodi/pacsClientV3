"""Synthetic, offscreen guards for study ownership and printable page fidelity."""
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QSpinBox


@pytest.fixture
def ui(monkeypatch, tmp_path):
    import PacsClient.utils.data_paths as paths
    from database import _pool
    monkeypatch.setattr(paths, "DATABASE_FILE", tmp_path / "isolated.db")
    monkeypatch.setattr(paths, "ATTACHMENTS_DIR", tmp_path / "attachments")
    with _pool._pool_lock:
        _pool._connection_pool.clear()
    from modules.printing.ui import printing_widget as mod
    from modules.printing.ui import film_preview_widget as preview
    from modules.printing.render import dicom_renderer as render
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(mod, "load_printing_config", lambda: {})
    monkeypatch.setattr(mod, "save_printing_config", lambda cfg: None)
    monkeypatch.setattr(mod.PrintingWidget, "_load_series", lambda self: None)
    monkeypatch.setattr(mod.PrintingWidget, "_load_filming_pages", lambda self: None)
    monkeypatch.setattr(mod.PrintingWidget, "_build_overlay_info", lambda self: {"patient_name": "Synthetic", "patient_id": "TEST"})
    monkeypatch.setattr(mod.QPrinterInfo, "availablePrinters", lambda: [])
    pix = QPixmap(16, 16)
    pix.fill()
    rendered = render.RenderedImage(pix, 16, 16, 1.0)
    monkeypatch.setattr(preview, "get_dicom_window_level", lambda path: (400, 40))
    monkeypatch.setattr(preview, "load_dicom_as_pixmap", lambda *args: rendered)
    monkeypatch.setattr(render, "load_dicom_as_pixmap", lambda *args: rendered)
    monkeypatch.setattr(preview, "compute_scout_reference_lines", lambda *args: (16, 16, []))
    monkeypatch.setattr(mod.QMessageBox, "warning", lambda *args: None)
    widget = mod.PrintingWidget(selected_patients=[{"study_uid": "synthetic-a", "patient_name": "Synthetic", "patient_id": "TEST"}])
    widget._selected_series = [{"series_uid": "synthetic-series"}]
    yield SimpleNamespace(widget=widget, mod=mod, preview=preview, render=render, app=app)
    widget.close()
    widget.deleteLater()
    app.processEvents()
    with _pool._pool_lock:
        _pool._connection_pool.clear()


def generate(ui, monkeypatch, count=8):
    paths = [f"synthetic-{i}" for i in range(count)]
    monkeypatch.setattr(ui.widget, "_collect_image_paths", lambda: paths.copy())
    from modules.printing.core.models import FilmLayout
    ui.widget._set_current_layout(FilmLayout(2, 2))
    ui.widget._generate_preview()
    return paths


def test_patient_switch_clears_old_document(ui, monkeypatch):
    generate(ui, monkeypatch)
    ui.widget._film_pixmap = QPixmap(2, 2)
    ui.widget.update_patients([{"study_uid": "synthetic-b", "patient_name": "Synthetic B", "patient_id": "TEST-B"}])
    assert ui.widget._selected_paths == []
    assert ui.widget._film_pixmap is None
    assert not ui.widget.preview_widget._tiles
    assert ui.widget.preview_widget.get_scout_path() is None


def test_empty_patient_selection_clears_identity(ui, monkeypatch):
    generate(ui, monkeypatch)
    ui.widget.update_patients([])
    assert ui.widget._selected_study_uid is None
    assert not ui.widget._selected_paths


def test_delete_keeps_other_pages(ui, monkeypatch):
    paths = generate(ui, monkeypatch)
    ui.widget._delete_selected_tiles()
    assert ui.widget._selected_paths == paths[1:]
    assert ui.widget._total_pages == 2


def test_scout_defaults_to_larger_preview_and_export_geometry(ui, monkeypatch):
    from modules.printing.layout.grid import GridLayoutEngine
    generate(ui, monkeypatch)
    preview = ui.widget.preview_widget
    preview.set_scout_path("synthetic-scout")
    assert preview._layout.scout_scale == 2.0
    captured = {}
    monkeypatch.setattr(ui.preview, "render_film", lambda *args, **kw: captured.update(layout=args[2]) or QPixmap(2,2))
    preview.export_film_pixmap()
    assert captured["layout"].scout_scale == 2.0
    preview.set_scout_path(None)
    assert preview._layout.scout_scale == 1.0


def test_legacy_scout_size_is_replaced_by_two_by_two(ui, monkeypatch):
    monkeypatch.setattr(ui.mod, "load_printing_config", lambda: {"scout_scale": 1.25})
    reopened = ui.mod.PrintingWidget()
    try:
        assert reopened._scout_scale == 2.0
    finally:
        reopened.close()
        reopened.deleteLater()


def test_two_by_two_scout_repages_without_losing_images(ui, monkeypatch):
    from modules.printing.core.models import FilmLayout
    paths = generate(ui, monkeypatch, 40)
    widget = ui.widget
    widget._set_current_layout(FilmLayout(4,5))
    widget.preview_widget.set_scout_path("synthetic-scout")
    assert len(widget.preview_widget._paths) == 20
    seen = []
    for page in range(widget._total_pages):
        widget._current_page = page
        widget._update_page_display()
        seen.extend(widget.preview_widget._paths)
    assert seen == paths
    widget._current_page = 0
    widget._update_page_display()
    widget.delete_page_btn.click()
    assert widget._selected_paths == paths[20:]
    widget.preview_widget.set_scout_path(None)
    assert len(widget.preview_widget._paths) == 20


def test_reference_labels_match_preview_export_and_page_image_numbers(ui, monkeypatch):
    from modules.printing.core.models import FilmLayout
    from modules.printing.render import film_renderer
    from PySide6.QtWidgets import QGraphicsTextItem
    generate(ui, monkeypatch, 40)
    lines = [(0, float(i % 16), 15, float(i % 16)) for i in range(20)]
    monkeypatch.setattr(ui.preview, "compute_scout_reference_lines", lambda *a: (16,16,lines))
    monkeypatch.setattr(film_renderer, "compute_scout_reference_lines", lambda *a: (16,16,lines))
    ui.widget._set_current_layout(FilmLayout(4,5))
    ui.widget.preview_widget.set_scout_path("synthetic-scout")
    ui.widget._next_page()
    preview = ui.widget.preview_widget
    labels = {item.toPlainText() for item in preview._scene.items()
              if isinstance(item,QGraphicsTextItem) and item.parentItem() is not None}
    assert labels == {"21","25","30","35","40"}
    printed = []
    monkeypatch.setattr(film_renderer, "_draw_scout_line_label", lambda painter,x,y,label,dpi: printed.append(label))
    assert preview.export_film_pixmap(dpi=30) is not None
    assert set(printed) == labels


def test_enlarged_scout_has_no_old_grid_line_through_it(ui, monkeypatch):
    from modules.printing.core.models import FilmSize, FilmLayout
    from modules.printing.render.film_renderer import render_film
    from PySide6.QtGui import QColor
    pix = QPixmap(100,100)
    pix.fill(QColor("red"))
    rendered = ui.render.RenderedImage(pix,100,100,1)
    film = render_film([rendered], FilmSize("synthetic",4,4/0.9),
                       FilmLayout(4,4,scout_scale=2.0), dpi=100,
                       overlay_info={"background_mode":"dark"})
    # The old first-column separator at about x=100 is inside the new scout.
    assert film.toImage().pixelColor(100,120).red() > 240
    assert film.toImage().pixelColor(100,120).green() < 10


@pytest.mark.parametrize("page", [0, 1, 2])
def test_delete_current_page_removes_only_that_sheet(ui, monkeypatch, page):
    paths = generate(ui, monkeypatch, 10)
    widget = ui.widget
    widget._current_page = page
    widget._update_page_display()
    widget.preview_widget._scene.clearSelection()
    widget.delete_page_btn.click()
    expected = paths[:page * 4] + paths[(page + 1) * 4:]
    assert widget._selected_paths == expected
    assert widget._total_pages == 2
    assert widget._current_page == min(page, 1)
    assert widget.preview_widget._paths == expected[widget._current_page * 4:][:4]
    assert widget._film_pixmap is None


@pytest.mark.parametrize("action", ["clear_all_btn", "delete_page_btn"])
def test_clear_or_delete_last_sheet_stays_empty_until_regenerated(ui, monkeypatch, action):
    paths = generate(ui, monkeypatch, 2 if action == "delete_page_btn" else 8)
    widget = ui.widget
    series = widget._selected_series.copy()
    getattr(widget, action).click()
    assert not widget._selected_paths
    assert not widget.preview_widget._tiles
    assert widget.preview_widget.get_scout_path() is None
    assert widget.page_label.text() == "Page 0/0"
    assert not widget.next_page_btn.isEnabled()
    assert not widget.prev_page_btn.isEnabled()
    assert widget._selected_series == series
    with monkeypatch.context() as patch:
        patch.setattr(widget, "_generate_preview", lambda: pytest.fail("Cleared sheets were regenerated implicitly"))
        widget._handle_print()
        widget._save_preview()
    widget._generate_preview()
    assert widget._selected_paths == paths


def test_adjustments_survive_navigation_and_layout(ui, monkeypatch):
    from modules.printing.core.models import FilmLayout, ViewportState
    generate(ui, monkeypatch)
    value = ViewportState(500, 0, 2, (0.1, 0.2))
    ui.widget.preview_widget._tiles[0].viewport = value
    ui.widget._next_page()
    ui.widget._prev_page()
    assert ui.widget.preview_widget._tiles[0].viewport == value
    ui.widget._set_current_layout(FilmLayout(3, 3))
    assert ui.widget.preview_widget._layout == FilmLayout(3, 3)
    assert ui.widget._total_pages == 1
    assert ui.widget.preview_widget._tiles[0].viewport == value


def test_adjustment_invalidates_saved_export(ui, monkeypatch):
    generate(ui, monkeypatch)
    ui.widget._film_pixmap = QPixmap(2, 2)
    ui.widget.preview_widget._apply_zoom(20)
    assert ui.widget._film_pixmap is None


def test_rebuild_cancels_pending_old_tiles(ui, monkeypatch):
    generate(ui, monkeypatch)
    ui.widget.preview_widget._apply_zoom(20)
    ui.widget._next_page()
    ui.widget.preview_widget._flush_rerender()
    assert not ui.widget.preview_widget._pending_tiles


def test_zero_window_level_is_preserved(ui, monkeypatch):
    from modules.printing.core.models import ViewportState
    generate(ui, monkeypatch)
    tile = ui.widget.preview_widget._tiles[0]
    tile.viewport = ViewportState(400, 0)
    ui.widget.preview_widget._apply_window_level(0, 0)
    assert tile.viewport.window_level == 0


def test_failed_preview_cannot_export_old_images(ui, monkeypatch):
    generate(ui, monkeypatch)
    monkeypatch.setattr(ui.widget, "_collect_image_paths", lambda: [])
    ui.widget._generate_preview()
    assert ui.widget.preview_widget.export_film_pixmap() is None


def test_saved_page_does_not_replace_active_export(ui, monkeypatch, tmp_path):
    generate(ui, monkeypatch)
    ui.widget._film_pixmap = None
    path = tmp_path / "synthetic.png"
    pix = QPixmap(2, 2)
    pix.fill()
    pix.save(str(path))
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.Accepted)
    ui.widget._load_saved_filming_page({"thumbnail_path": str(path)})
    assert ui.widget._film_pixmap is None


def test_header_settings_persist_and_font_controls_agree(ui, monkeypatch):
    saved = []
    monkeypatch.setattr(ui.mod, "save_printing_config", lambda cfg: saved.append(cfg))
    def accept(dialog):
        spins = dialog.findChildren(QSpinBox)
        spins[2].setValue(31)
        assert spins[1].value() == spins[2].value() == spins[3].value()
        return QDialog.Accepted
    monkeypatch.setattr(QDialog, "exec", accept)
    ui.widget._open_header_settings_dialog()
    assert saved[-1]["header"]["font_right_block"] == 31


def test_dicom_print_uses_composed_current_sheet_without_stride_padding(ui, monkeypatch):
    generate(ui, monkeypatch)
    ui.widget._next_page()
    image = QImage(5, 2, QImage.Format_Grayscale8)
    image.fill(123)
    monkeypatch.setattr(ui.widget, "_render_for_print", lambda dpi=300: QPixmap.fromImage(image))
    job = ui.widget._build_dicom_job()
    assert job.image_display_format == "STANDARD\\1,1"
    assert len(job.images) == 1
    assert job.images[0].columns == 5
    assert job.images[0].rows == 2
    assert job.images[0].pixel_data == bytes([123]) * 10


def test_bad_layout_validation_returns_errors():
    from modules.printing.core.models import PrintJob, FilmSize, PrinterConfig, SeriesSelection
    from modules.printing.core.validation import validate_print_job
    job = PrintJob("TEST", "Synthetic", "study", FilmSize("A4", 8, 11), None,
                   SeriesSelection("study", [], []), PrinterConfig("Test", "os"))
    assert "Invalid layout." in validate_print_job(job)


def test_range_change_cannot_save_stale_selection(ui, monkeypatch):
    generate(ui, monkeypatch)
    called = []
    monkeypatch.setattr(ui.widget, "_collect_image_paths", lambda: called.append(True) or [])
    ui.widget.range_start.setValue(2)
    ui.widget._save_preview()
    assert called
    assert not ui.widget._selected_paths


def test_dicom_submission_does_not_block_gui_and_marks_original_study(ui, monkeypatch):
    import threading
    from PySide6.QtCore import QThreadPool
    from modules.printing.printers import dicom_printer as printer
    generate(ui, monkeypatch)
    ui.widget.printer_type_combo.setCurrentText("DICOM Printer")
    pix = QPixmap(5, 5)
    pix.fill()
    monkeypatch.setattr(ui.widget, "_render_for_print", lambda dpi=300: pix)
    entered = threading.Event()
    release = threading.Event()
    observed = []
    marked = []
    def send(self, job):
        observed.append(threading.get_ident())
        entered.set()
        release.wait(2)
        return True
    monkeypatch.setattr(printer.DicomPrintHandler, "send_print_job", send)
    monkeypatch.setattr(ui.widget, "_mark_current_study_printed", marked.append)
    try:
        ui.widget._handle_print()
        assert entered.wait(1)
        assert observed[0] != threading.get_ident()
        assert not ui.widget.print_btn.isEnabled()
        ui.widget.update_patients([{"study_uid": "synthetic-b", "patient_name": "Synthetic B", "patient_id": "TEST-B"}])
    finally:
        release.set()
        assert QThreadPool.globalInstance().waitForDone(3000)
    ui.app.processEvents()
    assert marked == ["synthetic-a"]


def test_one_cell_with_scout_does_not_hide_selected_image(ui, monkeypatch):
    from modules.printing.core.models import FilmLayout
    generate(ui, monkeypatch)
    ui.widget.preview_widget.set_scout_path("synthetic-scout")
    ui.widget._set_current_layout(FilmLayout(1, 1))
    assert [tile.path for tile in ui.widget.preview_widget._tiles if not tile.is_scout] == ["synthetic-0"]


def test_series_selection_is_current_before_debounce_expires(ui):
    from PySide6.QtWidgets import QListWidgetItem
    from PySide6.QtCore import Qt
    item = QListWidgetItem("Synthetic series")
    latest = {"series_uid": "synthetic-latest"}
    item.setData(Qt.UserRole, latest)
    ui.widget.series_list.addItem(item)
    item.setSelected(True)
    assert ui.widget._ensure_series_selection() == [latest]


def test_dicom_landscape_matches_preview(ui, monkeypatch):
    generate(ui, monkeypatch)
    ui.widget._dicom_print_settings["film_orientation"] = "LANDSCAPE"
    ui.widget.printer_type_combo.setCurrentText("DICOM Printer")
    ui.widget._update_page_display()
    film = ui.widget.preview_widget._film_size
    assert film.width_in > film.height_in


def test_missing_printer_is_not_reported_ready(ui):
    assert "Ready" not in ui.widget.printer_status.text()
    assert not ui.widget.print_btn.isEnabled()


def test_scout_export_lines_follow_zoomed_pixels(ui, monkeypatch):
    from modules.printing.render import film_renderer as film
    from modules.printing.core.models import FilmLayout, FilmSize, ViewportState
    monkeypatch.setattr(film, "compute_scout_reference_lines", lambda *args: (16, 16, [(0, 6, 16, 6)]))
    monkeypatch.setattr(film, "_draw_header", lambda *args, **kwargs: None)
    monkeypatch.setattr(film, "_draw_scout_line_label", lambda *args: None)
    pix = QPixmap(8, 8)
    pix.fill("black")
    import inspect
    viewport_args = {"scout_viewport": ViewportState(zoom=2)} if "scout_viewport" in inspect.signature(film.render_film).parameters else {}
    result = film.render_film([ui.render.RenderedImage(pix, 8, 8, 1.0)],
                             FilmSize("Synthetic", 2, 3), FilmLayout(1, 1), dpi=100,
                             scout_info=("synthetic-scout", ["synthetic-slice"]),
                             **viewport_args)
    assert result.toImage().pixelColor(160, 115).name() == "#ffd933"


@pytest.mark.parametrize("mode,color,alpha", [("dark", "#000000", 255), ("white", "#ffffff", 255), ("none", "#000000", 0)])
def test_page_background_does_not_change_image_pixels(ui, monkeypatch, mode, color, alpha):
    from modules.printing.render import film_renderer as film
    from modules.printing.core.models import FilmLayout, FilmSize
    monkeypatch.setattr(film, "_draw_header", lambda *args, **kwargs: None)
    pix = QPixmap(20, 20)
    pix.fill("#456789")
    result = film.render_film([ui.render.RenderedImage(pix, 20, 20, 1)],
                             FilmSize("Synthetic", 4, 4), FilmLayout(2, 2), dpi=100,
                             overlay_info={"background_mode": mode}).toImage()
    assert result.pixelColor(300, 300).name() == color
    assert result.pixelColor(300, 300).alpha() == alpha
    assert result.pixelColor(100, 130).name() == "#456789"
    if mode == "none":
        assert result.pixelColor(199, 300).alpha() == 0  # The unpainted gutter remains transparent between opaque box edges.


def test_background_control_persists_and_updates_existing_page(ui, monkeypatch):
    generate(ui, monkeypatch)
    saved = []
    monkeypatch.setattr(ui.mod, "save_printing_config", lambda cfg: saved.append(cfg))
    ui.widget.background_combo.setCurrentIndex(ui.widget.background_combo.findData("none"))
    assert saved[-1]["background_mode"] == "none"
    assert ui.widget.preview_widget._overlay_info["background_mode"] == "none"
    assert ui.widget._film_pixmap is None
    monkeypatch.setattr(ui.mod, "load_printing_config", lambda: saved[-1])
    other = ui.mod.PrintingWidget()
    try:
        assert other.background_combo.currentData() == "none"
    finally:
        other.deleteLater()


def test_dicom_transparency_is_flattened_to_white_without_dark_margins(ui, monkeypatch):
    generate(ui, monkeypatch)
    pix = QPixmap(5, 2)
    pix.fill("transparent")
    image = pix.toImage()
    image.setPixelColor(2, 1, "#000000")
    ui.widget.background_combo.setCurrentIndex(ui.widget.background_combo.findData("none"))
    job = ui.widget._build_dicom_job(QPixmap.fromImage(image))
    assert job.images[0].pixel_data == b"\xff" * 7 + b"\x00" + b"\xff" * 2
    assert job.border_density == job.empty_image_density == "WHITE"


def mouse_event(ui, kind, index, button, modifiers=None, offset=(0, 0)):
    from PySide6.QtCore import Qt, QPointF
    from PySide6.QtGui import QMouseEvent
    preview = ui.widget.preview_widget
    item = preview._items[index]
    scene_pos = item.mapToScene(item.boundingRect().center())
    point = QPointF(preview.mapFromScene(scene_pos)) + QPointF(*offset)
    event = QMouseEvent(kind, point, point, button, button, modifiers or Qt.NoModifier)
    QApplication.sendEvent(preview.viewport(), event)


@pytest.mark.parametrize("tool", ["Pan", "Window Level / Window Width", "Zoom", "Default Mouse Function"])
def test_shift_group_survives_tool_switch_and_left_drag(ui, monkeypatch, tool):
    from PySide6.QtCore import Qt, QEvent
    from modules.printing.core.models import FilmLayout, ViewportState
    generate(ui, monkeypatch, 12)
    ui.widget.preview_widget.resize(900, 900)
    ui.widget._set_current_layout(FilmLayout(4, 4))
    for index, modifier in ((0, Qt.NoModifier), (9, Qt.ShiftModifier)):
        mouse_event(ui, QEvent.MouseButtonPress, index, Qt.LeftButton, modifier)
        mouse_event(ui, QEvent.MouseButtonRelease, index, Qt.LeftButton, modifier)
    preview = ui.widget.preview_widget
    assert len(preview._scene.selectedItems()) == 10
    ui.widget.left_drag_mode.setCurrentText(tool)
    assert len(preview._scene.selectedItems()) == 10
    mouse_event(ui, QEvent.MouseButtonPress, 4, Qt.LeftButton)
    mouse_event(ui, QEvent.MouseMove, 4, Qt.LeftButton, offset=(10, 10))
    mouse_event(ui, QEvent.MouseButtonRelease, 4, Qt.LeftButton, offset=(10, 10))
    assert len(preview._scene.selectedItems()) == 10
    assert all(tile.viewport != ViewportState() for tile in preview._tiles[:10])
    assert all(tile.viewport == ViewportState() for tile in preview._tiles[10:])


def test_ctrl_selection_gesture_does_not_edit_images(ui, monkeypatch):
    from PySide6.QtCore import Qt, QEvent
    from modules.printing.core.models import ViewportState
    generate(ui, monkeypatch)
    ui.widget.preview_widget.resize(900, 900)
    ui.widget._update_page_display()
    mouse_event(ui, QEvent.MouseButtonPress, 1, Qt.LeftButton, Qt.ControlModifier)
    mouse_event(ui, QEvent.MouseMove, 1, Qt.LeftButton, Qt.ControlModifier, (8, 8))
    mouse_event(ui, QEvent.MouseButtonRelease, 1, Qt.LeftButton, Qt.ControlModifier, (8, 8))
    assert all(tile.viewport == ViewportState() for tile in ui.widget.preview_widget._tiles)


def test_empty_selection_does_not_edit_an_arbitrary_first_image(ui, monkeypatch):
    from modules.printing.core.models import ViewportState
    generate(ui, monkeypatch)
    ui.widget.preview_widget._scene.clearSelection()
    ui.widget.preview_widget._apply_pan(10, 10)
    assert all(tile.viewport == ViewportState() for tile in ui.widget.preview_widget._tiles)


@pytest.mark.parametrize("button_name,field", [("RightButton", "zoom"), ("MiddleButton", "pan")])
def test_default_secondary_button_drag_keeps_group(ui, monkeypatch, button_name, field):
    from PySide6.QtCore import Qt, QEvent
    from modules.printing.core.models import ViewportState
    generate(ui, monkeypatch)
    preview = ui.widget.preview_widget
    preview.resize(900, 900)
    ui.widget._update_page_display()
    mouse_event(ui, QEvent.MouseButtonPress, 1, Qt.LeftButton, Qt.ControlModifier)
    mouse_event(ui, QEvent.MouseButtonRelease, 1, Qt.LeftButton, Qt.ControlModifier)
    button = getattr(Qt, button_name)
    mouse_event(ui, QEvent.MouseButtonPress, 0, button)
    mouse_event(ui, QEvent.MouseMove, 0, button, offset=(10, 10))
    mouse_event(ui, QEvent.MouseButtonRelease, 0, button, offset=(10, 10))
    assert len(preview._scene.selectedItems()) == 2
    assert all(getattr(t.viewport, field) != getattr(ViewportState(), field) for t in preview._tiles[:2])
    assert preview._tiles[2].viewport == ViewportState()


def test_click_unselected_image_replaces_group_and_ctrl_can_remove(ui, monkeypatch):
    from PySide6.QtCore import Qt, QEvent
    generate(ui, monkeypatch)
    preview = ui.widget.preview_widget
    preview.resize(900, 900)
    ui.widget._update_page_display()
    for index, mods in ((1, Qt.ControlModifier), (2, Qt.NoModifier), (2, Qt.ControlModifier)):
        mouse_event(ui, QEvent.MouseButtonPress, index, Qt.LeftButton, mods)
        mouse_event(ui, QEvent.MouseButtonRelease, index, Qt.LeftButton, mods)
        expected = 2 if index == 1 else (0 if mods == Qt.ControlModifier else 1)
        assert len(preview._scene.selectedItems()) == expected


def test_image_annotation_does_not_intercept_group_drag(ui, monkeypatch):
    from PySide6.QtCore import Qt, QEvent, QPointF
    from PySide6.QtWidgets import QGraphicsTextItem
    from PySide6.QtGui import QMouseEvent
    generate(ui, monkeypatch)
    preview = ui.widget.preview_widget
    preview.resize(900, 900)
    ui.widget._update_page_display()
    preview._items[1].setSelected(True)
    image = preview._items[0]
    decoration = QGraphicsTextItem("Synthetic overlay")
    decoration.setPos(image.scenePos() + image.boundingRect().center())
    decoration.setZValue(100)
    preview._scene.addItem(decoration)
    pos = QPointF(preview.mapFromScene(decoration.scenePos() + QPointF(2, 2)))
    event = QMouseEvent(QEvent.MouseButtonPress, pos, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(preview.viewport(), event)
    assert len(preview._scene.selectedItems()) == 2


@pytest.mark.parametrize("ctrl_first", [True, False])
def test_ctrl_selects_only_one_three_five_and_toggles_clicked_image(ui, monkeypatch, ctrl_first):
    from PySide6.QtCore import Qt, QEvent
    from modules.printing.core.models import FilmLayout
    generate(ui, monkeypatch, 12)
    preview = ui.widget.preview_widget
    preview.resize(900, 900)
    ui.widget._set_current_layout(FilmLayout(4, 4))
    for index in (0, 2, 4):
        modifier = Qt.ControlModifier if ctrl_first or index else Qt.NoModifier
        mouse_event(ui, QEvent.MouseButtonPress, index, Qt.LeftButton, modifier)
        mouse_event(ui, QEvent.MouseButtonRelease, index, Qt.LeftButton, modifier)
    assert {item.tile_index for item in preview._scene.selectedItems()} == {0, 2, 4}
    preview._apply_pan(10, 10)
    assert {i for i, tile in enumerate(preview._tiles) if tile.viewport.pan != (0, 0)} == {0, 2, 4}
    mouse_event(ui, QEvent.MouseButtonPress, 2, Qt.LeftButton, Qt.ControlModifier)
    mouse_event(ui, QEvent.MouseButtonRelease, 2, Qt.LeftButton, Qt.ControlModifier)
    assert {item.tile_index for item in preview._scene.selectedItems()} == {0, 4}


def test_shift_keeps_original_range_anchor(ui, monkeypatch):
    from PySide6.QtCore import Qt, QEvent
    from modules.printing.core.models import FilmLayout
    generate(ui, monkeypatch, 12)
    preview = ui.widget.preview_widget
    preview.resize(900, 900)
    ui.widget._set_current_layout(FilmLayout(4, 4))
    for index, modifier, expected in ((0, Qt.NoModifier, {0}), (9, Qt.ShiftModifier, set(range(10))), (4, Qt.ShiftModifier, set(range(5)))):
        mouse_event(ui, QEvent.MouseButtonPress, index, Qt.LeftButton, modifier)
        mouse_event(ui, QEvent.MouseButtonRelease, index, Qt.LeftButton, modifier)
        assert {item.tile_index for item in preview._scene.selectedItems()} == expected


@pytest.mark.parametrize("mode,expected", [("white","#000000"),("none","#000000"),("dark","#ffffff")])
def test_grid_stays_visible_in_preview_and_export_for_all_backgrounds(ui, monkeypatch, mode, expected):
    from modules.printing.render import film_renderer as film
    from modules.printing.core.models import FilmSize, FilmLayout
    from PySide6.QtWidgets import QGraphicsRectItem
    monkeypatch.setattr(film, "_draw_header", lambda *args, **kw: None)
    result = film.render_film([], FilmSize("Synthetic",4,4), FilmLayout(2,2), dpi=100,
                              overlay_info={"background_mode":mode}).toImage()
    border = result.pixelColor(197,300)
    assert border.alpha() == 255
    assert border.name() == expected
    assert result.pixelColor(300,300).alpha() == (0 if mode=="none" else 255)
    preview = ui.widget.preview_widget
    preview._scene.clear()
    preview._background_mode = mode
    preview._page_background, preview._page_ink = film.page_background(mode)
    preview._draw_preview_grid(FilmSize("Synthetic",4,3.6), FilmLayout(2,2),100,0.4)
    rectangles = [item for item in preview._scene.items() if isinstance(item,QGraphicsRectItem)]
    assert len(rectangles) == 16
    assert all(item.brush().color().name() == expected for item in rectangles)
