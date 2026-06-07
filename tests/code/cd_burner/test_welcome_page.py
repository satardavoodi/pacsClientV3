"""Branded welcome page: flow, Persian content, links, identity (headless)."""

import json

from pydicom.uid import generate_uid
from PySide6.QtCore import Qt

from modules.cd_burner.portable_viewer.welcome import (
    COMPANY_LINKS,
    COMPANY_STATEMENT_FA,
    WelcomePage,
)

from .conftest import write_ct_slice


def test_statement_and_links_content():
    assert "ایران نوبت" in COMPANY_STATEMENT_FA
    assert "AI-PACS" in COMPANY_STATEMENT_FA
    labels = [label for label, _url in COMPANY_LINKS]
    assert "irannobat.ir" in labels
    assert "ino724.com" in labels
    for _label, url in COMPANY_LINKS:
        assert url.startswith("https://")


def test_welcome_page_widget(qapp):
    page = WelcomePage()
    assert page.layoutDirection() == Qt.RightToLeft  # Persian-first
    assert page.statement_label.text() == COMPANY_STATEMENT_FA
    assert page.open_button.text() == "مشاهده تصاویر"
    assert len(page.link_buttons) == len(COMPANY_LINKS)

    fired = []
    page.proceed.connect(lambda: fired.append(True))
    page.open_button.click()
    assert fired

    # Center identity propagates and hides when absent
    page.set_center_identity({"name": "C1", "phone": "123"})
    assert page.center_label.isVisibleTo(page)
    assert "C1" in page.center_label.text()
    page.set_center_identity(None)
    assert not page.center_label.isVisibleTo(page)


def test_viewer_starts_on_welcome_and_proceeds(tmp_path, qapp):
    from modules.cd_burner.portable_viewer.viewer_app import LiteViewerWindow

    study_uid, series_uid = generate_uid(), generate_uid()
    write_ct_slice(tmp_path, series_uid, study_uid, 1)
    (tmp_path / "AIPACS_MEDIA_INFO.json").write_text(
        json.dumps({"center": {"name": "Alizadeh Imaging Center"}}), encoding="utf-8"
    )

    window = LiteViewerWindow(media_root=None)  # default: welcome first
    try:
        assert window.stack.currentIndex() == 0
        assert window.stack.currentWidget() is window.welcome_page
        assert not window._toolbar.isVisibleTo(window)

        # Manifest identity reaches the welcome page too
        window._apply_media_info(str(tmp_path))
        assert "Alizadeh Imaging Center" in window.welcome_page.center_label.text()

        # «مشاهده تصاویر» → viewer body, toolbar back
        window.welcome_page.open_button.click()
        assert window.stack.currentIndex() == 1
        assert window._toolbar.isVisibleTo(window)
    finally:
        window._pool.waitForDone(3000)
        window.close()


def test_no_welcome_flag_opens_viewer_directly(qapp):
    from modules.cd_burner.portable_viewer.viewer_app import LiteViewerWindow

    window = LiteViewerWindow(media_root=None, show_welcome=False)
    try:
        assert window.stack.currentIndex() == 1
        assert window._toolbar.isVisibleTo(window)
    finally:
        window._pool.waitForDone(3000)
        window.close()
