"""Synthetic SR cards share the real Home/patient thumbnail factory."""
import pytest
from PySide6.QtGui import QPixmap
from tests.code.ui_services.test_thumbnail_card_effect_lifetime import scene


@pytest.mark.parametrize('nested', [False, True])
def test_sr_card_has_document_preview_and_count(scene, nested):
    manager, _ = scene.managed()
    info = {'modality': 'SR', 'document_count': 14, 'image_count': 0}
    if nested:
        info = {'series': info}
    source = QPixmap(160, 120)
    source.fill()
    card = manager.create_thumbnail_widget(source, '99', thumbnail_index='99', series_info=info)
    assert card.count_label.text() == '14 documents'
    assert 'SR' in card.image_button.toolTip()
    assert card.image_button.icon().pixmap(160, 120).toImage() != source.toImage()
    manager._set_series_count_label_text('99', '14 images')
    assert card.count_label.text() == '14 documents'
    preview = card.image_button.icon().pixmap(160, 120).toImage()
    manager._apply_thumbnail_image('99', source.toImage())
    assert card.image_button.icon().pixmap(160, 120).toImage() == preview
    card.deleteLater()


def test_normal_image_card_keeps_its_pixels_and_count(scene):
    manager, _ = scene.managed()
    source = QPixmap(160, 120)
    source.fill()
    card = manager.create_thumbnail_widget(source, '2', thumbnail_index='2',
        series_info={'modality': 'MR', 'image_count': 20})
    assert card.count_label.text() == '20 images'
    assert card.image_button.icon().pixmap(160, 120).toImage() == source.toImage()
    assert card.image_button.series_number == '2'
    card.deleteLater()
