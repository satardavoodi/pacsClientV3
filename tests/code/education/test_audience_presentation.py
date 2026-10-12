"""Audience output shares one media surface and restores it on exit."""
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel


def test_audience_shares_live_surface_and_escape_restores_it():
    from modules.education.audience_presentation import AudiencePresentation
    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    layout = QVBoxLayout(owner)
    surface = QLabel('Synthetic slide')
    layout.addWidget(surface)
    owner.show()
    output = AudiencePresentation(surface, layout, owner)
    output.start(app.primaryScreen())
    app.processEvents()
    assert surface.window() is output
    surface.setText('Next slide')
    assert output.surface.text() == 'Next slide'
    assert set(output.findChildren(QLabel)) == {surface, output.message}
    QTest.keyClick(output, Qt.Key_Escape)
    app.processEvents()
    assert surface.parentWidget() is owner
    assert layout.indexOf(surface) == 0
    assert surface.isVisible() and not output.isVisible()
    owner.close()


def test_audience_dicom_boundary_blanks_stale_media_and_resumes():
    from modules.education.audience_presentation import AudiencePresentation
    app = QApplication.instance() or QApplication([])
    owner = QWidget(); layout = QVBoxLayout(owner)
    surface = QLabel('Previous media'); layout.addWidget(surface)
    output = AudiencePresentation(surface, layout, owner)
    output.start(app.primaryScreen())
    output.set_media_active(False)
    app.processEvents()
    assert surface.isHidden() and output.message.isVisible()
    output.set_media_active(True)
    app.processEvents()
    assert surface.isVisible() and output.message.isHidden()
    output.close()
    assert surface.parentWidget() is owner


def test_screen_removal_restores_surface_and_navigation_is_forwarded():
    from modules.education.audience_presentation import AudiencePresentation
    app = QApplication.instance() or QApplication([])
    owner = QWidget(); layout = QVBoxLayout(owner)
    surface = QLabel('Slide'); layout.addWidget(surface)
    output = AudiencePresentation(surface, layout, owner)
    steps=[]; output.step.connect(steps.append)
    output.start(app.primaryScreen())
    QTest.keyClick(output, Qt.Key_Right)
    QTest.keyClick(output, Qt.Key_Left)
    assert steps == [1, -1]
    output._screen_removed(app.primaryScreen())
    assert surface.parentWidget() is owner and not output.isVisible()
    owner.close()
