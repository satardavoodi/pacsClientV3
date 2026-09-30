"""Exercise Education against the real shared thumbnail scheduler/manager."""
import asyncio
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from PySide6.QtCore import Qt
from shiboken6 import isValid
from qasync import QEventLoop
from tests.code.ui_services.test_sidebar_bounded_build import make_owner
from tests.code.education.test_presentation_navigation import method


def test_education_revisit_preserves_shared_cards_and_study_switch_rebuilds(monkeypatch):
    app=QApplication.instance() or QApplication([])
    loop=QEventLoop(app);asyncio.set_event_loop(loop)
    owner=make_owner(6)
    from PacsClient.pacs.patient_tab.utils.thumbnail_image_source_service import ThumbnailImageSourceService
    def prepare(*a,**kw):
        image=QImage(8,8,QImage.Format_RGB32);image.fill(Qt.white);return image
    monkeypatch.setattr(ThumbnailImageSourceService,'prepare_image',prepare)
    original=owner.show_exist_thumbnails
    owner.show_exist_thumbnails=lambda:original(thumbnail_files=[Path(f'{i}.png') for i in range(1,7)])
    populate=method('_populate_education_series_rail')
    async def settle():
        task=getattr(owner,'_sidebar_build_task',None)
        if task:await task
        await asyncio.sleep(.02)
    async def run():
        populate(owner);await settle()
        before=dict(owner.thumbnail_manager.series_widgets)
        assert len(before)==6
        populate(owner);await settle()
        assert all(isValid(w) and owner.thumb_grid.indexOf(w)>=0 for w in before.values())
        assert owner.thumbnail_manager.series_widgets==before
        owner.study_uid='synthetic-b';owner.import_folder_path='synthetic-second-root'
        owner._server_series_info={}
        populate(owner);await settle()
        after=dict(owner.thumbnail_manager.series_widgets)
        assert len(after)==6
        assert all(after[key] is not before[key] for key in after)
        assert all(isValid(w) and owner.thumb_grid.indexOf(w)>=0 for w in after.values())
        owner.study_uid='synthetic-a';owner.import_folder_path='synthetic-root'
        populate(owner);await settle()
        returned=dict(owner.thumbnail_manager.series_widgets)
        assert len(returned)==6 and all(returned[k] is not after[k] for k in returned)
        populate(owner);await settle()
        assert returned==owner.thumbnail_manager.series_widgets
        assert all(isValid(w) and owner.thumb_grid.indexOf(w)>=0 for w in returned.values())
    try:
        with loop:loop.run_until_complete(run())
    finally:
        owner.thumbnail_manager.dispose();owner.close();owner.deleteLater();app.processEvents();loop.close()
