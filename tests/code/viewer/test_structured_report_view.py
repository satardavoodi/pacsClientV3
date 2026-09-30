"""Synthetic SR documents; no clinical database or source files are used."""
import pytest
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, EnhancedSRStorage, generate_uid


def report():
    ds = Dataset()
    ds.SOPClassUID = EnhancedSRStorage
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.SOPInstanceUID = generate_uid()
    ds.CompletionFlag = "PARTIAL"
    ds.VerificationFlag = "UNVERIFIED"
    ds.ValueType = "CONTAINER"
    ds.ConceptNameCodeSequence = [code("Acquisition report")]
    text = Dataset()
    text.ValueType = "TEXT"
    text.ConceptNameCodeSequence = [code("Protocol")]
    text.TextValue = "Synthetic <b>protocol</b>"
    num = Dataset()
    num.ValueType = "NUM"
    num.ConceptNameCodeSequence = [code("Thickness")]
    measure = Dataset()
    measure.NumericValue = "3.5"
    measure.MeasurementUnitsCodeSequence = [code("millimeter", "mm")]
    num.MeasuredValueSequence = [measure]
    ds.ContentSequence = [text, num]
    return ds


def code(meaning, value="test"):
    ds = Dataset()
    ds.CodeMeaning = meaning
    ds.CodeValue = value
    ds.CodingSchemeDesignator = "99TEST"
    return ds


def save(ds, path):
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = ds.SOPClassUID
    meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    file = FileDataset(str(path), ds, file_meta=meta, preamble=b"\0" * 128)
    file.is_little_endian = True
    file.is_implicit_VR = False
    file.save_as(path, write_like_original=False)


def test_report_preserves_labels_units_and_document_status():
    from PacsClient.utils.structured_report import render_report
    result = render_report(report())
    assert "PARTIAL" in result and "UNVERIFIED" in result
    assert "Protocol: Synthetic <b>protocol</b>" in result
    assert "Thickness: 3.5 mm" in result


def test_pixel_image_is_not_a_report():
    from PacsClient.utils.structured_report import render_report
    ds = report()
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.4"
    with pytest.raises(ValueError):
        render_report(ds)


def test_reader_rejects_other_study_and_series(tmp_path):
    from PacsClient.utils.structured_report import load_reports
    ds = report()
    save(ds, tmp_path / "one.dcm")
    result = load_reports(str(tmp_path), ds.StudyInstanceUID, ds.SeriesInstanceUID)
    assert len(result) == 1 and "Thickness" in result[0][1]
    with pytest.raises(ValueError):
        load_reports(str(tmp_path), generate_uid(), ds.SeriesInstanceUID)
    with pytest.raises(ValueError):
        load_reports(str(tmp_path), ds.StudyInstanceUID, generate_uid())


def test_text_and_recursion_are_bounded():
    from PacsClient.utils.structured_report import render_report
    ds = report()
    ds.ContentSequence[0].TextValue = "x" * 100000
    result = render_report(ds)
    assert len(result) < 40000
    assert "truncated" in result


def test_multiple_documents_are_preserved(tmp_path):
    from PacsClient.utils.structured_report import load_reports
    ds = report()
    for i in range(3):
        ds.SOPInstanceUID = generate_uid()
        ds.InstanceNumber = i + 1
        save(ds, tmp_path / f"{i}.dcm")
    assert len(load_reports(str(tmp_path), ds.StudyInstanceUID, ds.SeriesInstanceUID)) == 3


@pytest.fixture
def panel(monkeypatch):
    from PySide6.QtWidgets import QApplication, QWidget
    from PacsClient.pacs.patient_tab.ui.patient_ui import structured_report_view as view
    app = QApplication.instance() or QApplication([])
    jobs = []
    class Pool:
        def start(self, job):
            jobs.append(job)
    class Threads:
        @staticmethod
        def globalInstance():
            return Pool()
    monkeypatch.setattr(view, "QThreadPool", Threads)
    host = QWidget()
    host.resize(640, 480)
    result = view.StructuredReportPanel(host)
    yield result, jobs, app
    host.close()
    host.deleteLater()
    app.processEvents()


def test_stale_report_cannot_replace_new_selection(panel):
    widget, jobs, _ = panel
    widget.begin(("first", "1", "2"))
    old = widget.generation
    widget.begin(("second", "3", "4"))
    widget._receive(old, (("old", "wrong report"),), "")
    assert widget.text.toPlainText() == "Loading structured report..."
    widget._receive(widget.generation, (("new", "<b>literal text</b>"),), "")
    assert widget.text.toPlainText() == "<b>literal text</b>"
    widget.dismiss()
    widget._receive(widget.generation - 1, (("late", "old"),), "")
    assert widget.text.toPlainText() == "" and not widget.active
    assert len(jobs) == 2
    assert jobs[0].cancelled.is_set() and jobs[1].cancelled.is_set()


def test_report_navigation(panel):
    widget, _, _ = panel
    widget.begin(("unused", "1", "2"))
    widget._receive(widget.generation, (("one", "first"), ("two", "second")), "")
    widget.selector.setCurrentIndex(1)
    assert widget.text.toPlainText() == "second"
    assert widget.selector.isEnabled()


def test_router_consumes_sr_and_restores_image_route(panel):
    from types import SimpleNamespace
    from PacsClient.pacs.patient_tab.ui.patient_ui.structured_report_view import route_report
    widget, jobs, _ = panel
    host = widget.parentWidget()
    host._structured_report_panel = widget
    calls = []
    controller = SimpleNamespace(
        parent_widget=SimpleNamespace(_server_series_info={"99": {"modality": "SR"}}),
        _next_request_token=lambda w: calls.append("invalidate"),
        _hide_spinner_for_widget=lambda w: calls.append("hide"),
        _resolve_series_ref=lambda key: SimpleNamespace(
            series_path="exact-folder", study_uid="1", series_uid="2", source="entry"),
    )
    assert route_report(controller, host, "99") is True
    assert calls == ["invalidate", "hide"]
    assert jobs[0].identity == ("exact-folder", "1", "2")
    assert host._structured_report_active
    assert route_report(controller, host, "1") is False
    assert not host._structured_report_active and not widget.active


def test_sr_blocks_even_untokened_image_apply():
    import ast
    from pathlib import Path
    from types import SimpleNamespace
    path = Path("PacsClient/pacs/patient_tab/ui/patient_ui/_vc_switch.py")
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == "_is_request_current")
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
    assert namespace[method.name](None, SimpleNamespace(_structured_report_active=True), None) is False


def test_worker_delivers_document_on_queued_ui_connection(tmp_path, monkeypatch):
    import threading
    import time
    from PySide6.QtWidgets import QApplication, QWidget
    from PacsClient.pacs.patient_tab.ui.patient_ui import structured_report_view as view
    ds = report()
    save(ds, tmp_path / "synthetic.dcm")
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    widget = view.StructuredReportPanel(host)
    threads = []
    original = view.load_reports
    def read(*args, **kwargs):
        threads.append(threading.get_ident())
        return original(*args, **kwargs)
    monkeypatch.setattr(view, "load_reports", read)
    widget.begin((str(tmp_path), ds.StudyInstanceUID, ds.SeriesInstanceUID))
    deadline = time.monotonic() + 4
    while not widget.documents and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert len(widget.documents) == 1
    assert "Thickness: 3.5 mm" in widget.text.toPlainText()
    assert threads and threads[0] != threading.get_ident()
    widget.dismiss()
    host.deleteLater()
    app.processEvents()


def test_cancelled_reader_does_not_touch_filesystem(monkeypatch):
    from PacsClient.utils import structured_report as sr
    monkeypatch.setattr(sr.Path, "iterdir", lambda *_: pytest.fail("Cancelled read touched disk"))
    assert sr.load_reports("unused", "1", "2", cancelled=lambda: True) == ()


def test_image_tools_cannot_consume_retained_image_behind_report():
    import ast
    from pathlib import Path
    from types import SimpleNamespace
    path = Path("PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py")
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    names = {"toggle_capture", "toggle_new_curve_mpr", "toggle_zeta_mpr",
             "toggle_window_level", "_on_ai_analysis_clicked", "_capture_active_layout",
             "toggle_sync_point", "_toggle_lock_sync", "_apply_default_wl_preset"}
    target = SimpleNamespace(_structured_report_active=True)
    owner = SimpleNamespace(patient_widget=SimpleNamespace(selected_widget=target))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in names:
            namespace = {}
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
            args = (target,) if "selected_widget" in [arg.arg for arg in node.args.args] else ()
            assert namespace[node.name](owner, *args) is None
