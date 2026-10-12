"""Course covers retain every edge in both Education card implementations."""
import pytest
import time
from PySide6.QtWidgets import QApplication,QLabel
from PySide6.QtGui import QImage,QColor
from PySide6.QtCore import QPoint


@pytest.mark.parametrize('modern',[True,False])
@pytest.mark.parametrize('size',[(1000,200),(200,1000)])
def test_course_card_contains_full_cover_without_cropping(tmp_path,modern,size):
    app=QApplication.instance() or QApplication([])
    image=QImage(*size,QImage.Format_RGB32);image.fill(QColor('navy'))
    for y in range(size[1]):
        image.setPixelColor(0,y,QColor('red'));image.setPixelColor(size[0]-1,y,QColor('green'))
    path=tmp_path/'cover.png';assert image.save(str(path))
    if modern:
        from modules.education.education_module_redesigned import ModernCourseCard as Card
    else:
        from modules.education.education_main_widget import CourseCardWidget as Card
    card=Card({'course_pk':1,'course_name':'Synthetic teaching course','thumbnail_path':str(path)})
    card.show();app.processEvents()
    deadline = time.monotonic() + 3
    covers = []
    while not covers and time.monotonic() < deadline:
        app.processEvents()
        covers=[w for w in card.findChildren(QLabel) if w.pixmap() is not None and not w.pixmap().isNull()]
    assert len(covers)==1
    label=covers[0];pixmap=label.pixmap()
    max_width,max_height=(168,168) if modern else (294,140)
    assert pixmap.width()<=max_width and pixmap.height()<=max_height
    assert abs(pixmap.width()/pixmap.height()-size[0]/size[1])<0.2
    assert pixmap.width()<=label.width() and pixmap.height()<=label.height()
    assert abs(label.mapTo(card,QPoint(0,0)).x()+label.width()/2-card.width()/2)<=2
    card.close()
