"""PHI-free terminal diagnostics for actual asynchronous sidebar generations."""
import asyncio
import logging
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from PySide6.QtCore import Qt
from qasync import QEventLoop
from tests.code.ui_services.test_sidebar_bounded_build import make_owner

@pytest.mark.parametrize("mode", ["complete", "cancel_before_start", "path_changed", "inactive",
                                 "prepare_error", "changed_after_reservation", "cancel_in_worker",
                                 "native_deleted", "empty_plan", "hidden_cards", "apply_error"])
def test_sidebar_generation_is_observable_and_terminal(monkeypatch, caplog, mode):
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    loop = QEventLoop(app); asyncio.set_event_loop(loop)
    owner = make_owner(2)
    if mode == 'apply_error':
        def fail_apply(*args, **kwargs):
            raise OSError('synthetic-private-path')
        owner.add_thumbnail_to_thumbnail_layout = fail_apply
    if mode == 'hidden_cards':
        original_add = owner.add_thumbnail_to_thumbnail_layout
        def add_hidden(*args, **kwargs):
            result = original_add(*args, **kwargs)
            owner.thumbnail_manager.series_widgets[args[2]].hide()
            return result
        owner.add_thumbnail_to_thumbnail_layout = add_hidden
    from PacsClient.pacs.patient_tab.utils.thumbnail_image_source_service import ThumbnailImageSourceService
    def image(*a, **kw):
        if mode == "prepare_error":
            raise OSError("synthetic-private-path")
        if mode == "changed_after_reservation":
            loop.call_soon_threadsafe(setattr, owner, "import_folder_path", "synthetic-replaced")
        if mode == "cancel_in_worker":
            loop.call_soon_threadsafe(owner._sidebar_build_task.cancel)
        if mode == "native_deleted":
            from shiboken6 import delete
            loop.call_soon_threadsafe(delete, owner)
        result = QImage(8, 8, QImage.Format_RGB32); result.fill(Qt.white); return result
    monkeypatch.setattr(ThumbnailImageSourceService, "prepare_image", image)
    caplog.set_level(logging.INFO)
    async def run():
        if mode == "inactive": owner._is_active_patient_tab = False
        if mode == "empty_plan":
            from PacsClient.pacs.patient_tab.utils.thumbnail_batch_runner import start_sidebar_build
            start_sidebar_build(owner, loop, files=[], list_files=lambda *a: [])
        else:
            owner.show_exist_thumbnails(thumbnail_files=[Path("1.png"), Path("2.png")])
        task = owner._sidebar_build_task
        if mode == "cancel_before_start": task.cancel()
        if mode == "path_changed": owner.import_folder_path = "synthetic-replaced"
        if mode == "inactive":
            await asyncio.sleep(.01)
            owner._is_active_patient_tab = True
            owner._set_thumbnail_presentation_active(True)
        try: await task
        except asyncio.CancelledError: pass
        await asyncio.sleep(.01)
    try:
        with loop: loop.run_until_complete(run())
        records = [r for r in caplog.records if str(r.msg).startswith("[CONTENT-DIAG]")]
        stages = [r.stage for r in records]
        assert "scheduled" in stages
        terminal = [r for r in records if r.stage in {"completed", "cancelled", "invalidated", "failed"}]
        assert len(terminal) == 1
        expected = {"complete":"completed", "inactive":"completed",
                    "cancel_before_start":"cancelled", "path_changed":"invalidated",
                    "prepare_error":"failed", "changed_after_reservation":"invalidated",
                    "cancel_in_worker":"cancelled", "native_deleted":"invalidated",
                    "empty_plan":"completed", "hidden_cards":"completed", "apply_error":"failed"}[mode]
        assert terminal[0].stage == expected
        if mode == "inactive": assert "visibility_wait" in stages
        if mode in {"complete", "inactive"}:
            assert "first_card_prepared" in stages and "first_card_applied" in stages
        messages = " ".join(r.getMessage() for r in records)
        assert "synthetic-root" not in messages and "synthetic-a" not in messages
        assert "synthetic-private-path" not in messages
        assert all(r.study_uid == "-" and r.series_uid == "-" for r in records)
        if mode in {"changed_after_reservation", "prepare_error", "cancel_in_worker"}:
            assert "reserved" in stages
        if mode == "changed_after_reservation":
            assert "'folder_equal': False" in terminal[0].getMessage()
        if mode in {"complete", "inactive"}:
            assert len(owner.thumbnail_manager.series_widgets) == 2
        if mode == 'hidden_cards':
            assert "'admitted': 2" in terminal[0].getMessage()
            assert "'representative_visible': False" in terminal[0].getMessage()
        if mode == 'prepare_error':
            assert 'phase=image_worker' in terminal[0].getMessage()
            assert "'error_kind': 1" in terminal[0].getMessage()
        if mode == 'apply_error':
            assert 'phase=applying' in terminal[0].getMessage()
    finally:
        from shiboken6 import isValid
        owner.thumbnail_manager.dispose()
        if isValid(owner):
            owner.close(); owner.deleteLater()
        app.processEvents(); asyncio.set_event_loop(None)


def test_trace_neutralizes_inherited_context_and_aggregates_without_content(caplog):
    from PacsClient.utils.diagnostic_logging import (
        ContentDiagnosticTrace, ContextEnricherFilter, _LOG_CONTEXT,
        content_diagnostic_work, content_diagnostic_phase,
    )
    caplog.set_level(logging.INFO)
    token = _LOG_CONTEXT.set(dict(study_uid="synthetic-private-uid", series_uid="synthetic-private-series"))
    try:
        trace = ContentDiagnosticTrace("education_open")
        with trace.bind(), content_diagnostic_phase("library_construct"):
            for _ in range(4):
                assert content_diagnostic_work("library_query", lambda: 3) == 3
        trace.finish("completed", unsafe="synthetic-private-text")
        trace.finish("failed")
    finally:
        _LOG_CONTEXT.reset(token)
    records = [r for r in caplog.records if str(r.msg).startswith("[CONTENT-DIAG]")]
    for record in records:
        ContextEnricherFilter().filter(record)
        assert record.study_uid == record.series_uid == "-"
        assert "synthetic-private" not in record.getMessage()
    assert len(records) == 3
    assert "'library_query_count': 4" in records[-1].getMessage()


def test_synchronous_sidebar_setup_failure_has_terminal(caplog):
    from PacsClient.pacs.patient_tab.utils.thumbnail_batch_runner import start_sidebar_build
    app = QApplication.instance() or QApplication([])
    owner = make_owner(1)
    owner._server_series_info = {'1': object()}
    caplog.set_level(logging.INFO)
    try:
        with pytest.raises(TypeError):
            start_sidebar_build(owner, None, files=[], list_files=lambda *a: [])
        records = [r for r in caplog.records if str(r.msg).startswith('[CONTENT-DIAG]')]
        assert [r.stage for r in records] == ['scheduled', 'failed']
        assert 'phase=setup' in records[-1].getMessage()
        assert "'error_kind': 5" in records[-1].getMessage()
    finally:
        owner.thumbnail_manager.dispose(); owner.close(); owner.deleteLater(); app.processEvents()


def test_overlapping_worker_cannot_relabel_gui_admission_failure(monkeypatch, caplog):
    import threading
    from PacsClient.pacs.patient_tab.utils.thumbnail_image_source_service import ThumbnailImageSourceService
    app = QApplication.instance() or QApplication([]); app.setQuitOnLastWindowClosed(False)
    loop = QEventLoop(app); asyncio.set_event_loop(loop)
    owner = make_owner(2)
    second_completeness = threading.Event()
    release = threading.Event()
    gui_entered = threading.Event()
    image_calls = []
    calls = []
    def completeness(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            second_completeness.set()
            assert release.wait(2)
        return False
    owner._is_series_downloaded = completeness
    def image(*args):
        image_calls.append(1)
        if len(image_calls) == 2:
            assert gui_entered.wait(2)
        result = QImage(8, 8, QImage.Format_RGB32); result.fill(Qt.white); return result
    monkeypatch.setattr(ThumbnailImageSourceService, 'prepare_image', image)
    def fail_admission(*args, **kwargs):
        gui_entered.set()
        assert second_completeness.wait(2), 'Force worker phase change during GUI admission'
        raise OSError('synthetic-private-error')
    owner.add_thumbnail_to_thumbnail_layout = fail_admission
    caplog.set_level(logging.INFO)
    async def run():
        owner.show_exist_thumbnails(thumbnail_files=[Path('1.png'),Path('2.png')])
        await owner._sidebar_build_task
    try:
        with loop: loop.run_until_complete(run())
        terminal = [r for r in caplog.records if str(r.msg).startswith('[CONTENT-DIAG]') and r.stage == 'failed']
        assert len(terminal) == 1
        assert 'phase=applying' in terminal[0].getMessage()
        assert "'error_kind': 1" in terminal[0].getMessage()
        assert 'synthetic-private-error' not in terminal[0].getMessage()
    finally:
        release.set()
        owner.thumbnail_manager.dispose(); owner.close(); owner.deleteLater()
        app.processEvents(); asyncio.set_event_loop(None)
