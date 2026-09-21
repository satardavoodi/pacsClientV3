"""Synthetic interaction and evidence guards, never clinical fixtures."""
import numpy as np
import pytest
from test_eagle_eye_total_spine import view, body, qapp


def test_perpendicular_construction_stays_inside_and_retains_obtuse_angle():
    from modules.ai_imaging.eagle_eye_total_spine.annotations import perpendicular_construction
    for angle in (0, 20, 60):
        upper = np.array(list(body(240, 150, -angle, height=100).values())[:2])
        lower = np.array(list(body(240, 700, angle, height=100).values())[2:])
        result = perpendicular_construction(upper, lower, (1000, 500), (2., 1.))
        for pair, normal in zip((upper, lower), result['normals']):
            d = (pair[1]-pair[0])*[1, 2]
            n = (np.array(normal[1])-normal[0])*[1, 2]
            assert np.dot(d, n) == pytest.approx(0, abs=1e-7)
        all_points = np.array([p for line in result['lines'] for p in line['points']])
        assert (all_points >= 0).all()
        assert (all_points < [500, 1000]).all()
        expected = 2*np.degrees(np.arctan(2*np.tan(np.radians(angle))))
        assert result['angle_deg'] == pytest.approx(expected)


def test_anchor_mapping_preserves_known_missing_levels_and_rejects_collision():
    from modules.ai_imaging.eagle_eye_total_spine.editing import level_mapping
    assert level_mapping(['T12', 'L2', 'L3'], 'L3', 'L5', True) == {'T12':'L2', 'L2':'L4', 'L3':'L5'}
    with pytest.raises(ValueError): level_mapping(['L4', 'L5'], 'L4', 'L5', False)
    with pytest.raises(ValueError): level_mapping(['C1', 'L5'], 'L5', 'L4', True)


def test_editor_edits_are_atomic_and_pedicle_evidence_invalidates_grade(qapp):
    from modules.ai_imaging.eagle_eye_total_spine.widget import ProjectionEditor
    e = ProjectionEditor('coronal'); v = view(); e.accept_image(v['image'])
    e.points = v['points']; e.curves = v['curves']; e.review.setChecked(True)
    old = np.array([e.points['T4']['superior_left'], e.points['T4']['superior_right']])
    e._segment_changed('T4', 'superior', (old+[8, 12]).tolist())
    assert not e.review.isChecked()
    assert e.points['T4']['superior_left'] == pytest.approx((old+[8, 12])[0])
    e.rotations = [dict(level='T4', grade=1, direction='left')]
    e._point_changed('pedicle:T4', 'image_left', 230, 170)
    assert e.snapshot()['pedicles']['T4']['image_left'] == [230, 170]
    assert e.rotations == []
    e._apply_level_mapping({'T4':'T5', 'T8':'T9', 'T12':'L1'})
    assert 'T5' in e.pedicles and e.curves[0]['upper'] == 'T5'
    assert e.curves[0]['apex'] == 'T9'
    e.clear_image(); assert not e.pedicles
    e.close()


def test_pedicles_and_reference_proposals_are_visible_without_fake_rotation():
    from modules.ai_imaging.eagle_eye_total_spine.annotations import overlay_primitives
    from modules.ai_imaging.eagle_eye_total_spine.measurements import measure_view
    v = view(); v['markers'] = {'Sacral center':[240, 950]}
    v['pedicles'] = {'T8': {'image_left':[290, 402], 'image_right':[310, 402]}}
    m = measure_view(v); overlay = overlay_primitives(v, m)
    text = ' '.join(x['text'] for x in overlay['labels'])
    assert 'pedicle' in text and 'stable' in text and 'proposal' in text
    assert not m['rotations']
    v['pedicles']['T8']['image_left'] = [-1, 10]
    with pytest.raises(ValueError): measure_view(v)


def test_mouse_drags_segment_then_endpoint_and_body_badge_renumbers(qapp):
    from PySide6.QtCore import Qt, QPointF, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QComboBox
    from modules.ai_imaging.eagle_eye_total_spine.widget import ProjectionEditor
    from modules.ai_imaging.eagle_eye_total_spine.editing import LevelBadge
    e = ProjectionEditor('coronal'); v = view(); e.resize(1500, 900); e.show()
    e.accept_image(v['image']); e.points = v['points']; e.curves = v['curves']
    e.canvas.set_points(e.points); e.recalculate(); e.canvas.fit(); qapp.processEvents()
    def drag(a, b):
        start = e.canvas.mapFromScene(QPointF(*a)); end = e.canvas.mapFromScene(QPointF(*b))
        QTest.mousePress(e.canvas.viewport(), Qt.LeftButton, pos=start)
        QTest.mouseMove(e.canvas.viewport(), end, delay=20)
        QTest.mouseRelease(e.canvas.viewport(), Qt.LeftButton, pos=end)
        qapp.processEvents()
    before = np.array([e.points['T4']['superior_left'], e.points['T4']['superior_right']])
    center = before.mean(0); drag(center, center+[15, 20])
    after = np.array([e.points['T4']['superior_left'], e.points['T4']['superior_right']])
    assert after-before == pytest.approx(np.tile([15, 20], (2, 1)), abs=2)
    assert after[1]-after[0] == pytest.approx(before[1]-before[0])
    drag(after[1], after[1]+[3, 10])
    assert e.points['T4']['superior_right'][1] > after[1,1]+7
    badge = next(i for i in e.canvas.lines if isinstance(i, LevelBadge) and i.level == 'T4')
    errors = []
    def accept_numbering():
        dialog = QApplication.activeModalWidget()
        if not isinstance(dialog, QDialog): errors.append('No numbering dialog'); return
        dialog.findChild(QComboBox).setCurrentText('T5'); dialog.accept()
    QTimer.singleShot(50, accept_numbering)
    position = e.canvas.mapFromScene(badge.pos())
    QTest.mouseClick(e.canvas.viewport(), Qt.LeftButton, pos=position)
    qapp.processEvents()
    assert not errors and 'T5' in e.points and 'T4' not in e.points
    assert e.curves[0]['apex'] == 'T9'
    e._undo_edit(); assert 'T4' in e.points and 'T5' not in e.points
    e.close()


def test_anchor_candidates_require_review_and_undo_preserves_originals(qapp):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QCheckBox
    from modules.ai_imaging.eagle_eye_total_spine.widget import ProjectionEditor
    e = ProjectionEditor('coronal'); e.accept_image(view()['image'])
    candidates = [dict(corners=list(body(240, y).values())) for y in (100, 200, 300)]
    e.accept_candidates(dict(candidates=candidates, model='synthetic'))
    e.candidate.setCurrentIndex(2); e.level.setCurrentText('L5')
    def confirm():
        dialog = QApplication.activeModalWidget()
        dialog.findChild(QCheckBox).setChecked(True); dialog.accept()
    QTimer.singleShot(20, confirm); e._candidate_numbering()
    assert set(e.points) == {'L3', 'L4', 'L5'} and not e.candidates
    assert not e.review.isChecked()
    e._undo_edit(); assert not e.points and len(e.candidates) == 3
    e._set_region([10, 10, 490, 990]); assert not e._undo and not e.candidates
    e.close()


def test_renumber_rejects_unassigned_evidence_collision_without_mutation(qapp):
    from modules.ai_imaging.eagle_eye_total_spine.widget import ProjectionEditor
    e = ProjectionEditor('coronal'); e.accept_image(view()['image'])
    e.points = {'T4':body(240, 150)}
    e.pedicles = {'T4':{'image_left':[230,160]}, 'T5':{'image_left':[230,200]}}
    with pytest.raises(ValueError): e._apply_level_mapping({'T4':'T5'})
    assert set(e.points) == {'T4'} and set(e.pedicles) == {'T4','T5'} and not e._undo
    e.close()


def test_multiple_curve_constructions_have_separate_inside_image_slots():
    from modules.ai_imaging.eagle_eye_total_spine.annotations import perpendicular_construction
    upper=np.array([[100, 100],[200,80]]); lower=np.array([[100,500],[200,520]])
    origins=[]
    for slot in range(5):
        construction=perpendicular_construction(upper,lower,(1000,500),(1,1),slot,5)
        origins.append(construction['label_at'][1])
        all_points=np.array([p for line in construction['lines'] for p in line['points']])
        assert (all_points >= 0).all() and (all_points < [500,1000]).all()
    assert min(np.diff(origins)) > 100


def test_unnumbered_candidate_click_drag_and_undo(qapp):
    from PySide6.QtCore import Qt, QPointF
    from PySide6.QtTest import QTest
    from modules.ai_imaging.eagle_eye_total_spine.widget import ProjectionEditor
    e=ProjectionEditor('coronal'); e.resize(1500,900); e.show()
    e.accept_image(view()['image'])
    e.accept_candidates({'candidates':[{'corners':list(body(240,y,height=65).values())} for y in (100,350)]})
    e.canvas.fit(); qapp.processEvents()
    def click(point):
        QTest.mouseClick(e.canvas.viewport(),Qt.LeftButton,pos=e.canvas.mapFromScene(QPointF(*point)))
        qapp.processEvents()
    click([235,380])
    assert e.candidate.currentIndex()==1
    before=np.array(e.candidates[1]['corners']); center=before[:2].mean(0)
    start=e.canvas.mapFromScene(QPointF(*center)); end=e.canvas.mapFromScene(QPointF(*(center+[10,12])))
    QTest.mousePress(e.canvas.viewport(),Qt.LeftButton,pos=start)
    QTest.mouseMove(e.canvas.viewport(),end,delay=20)
    QTest.mouseRelease(e.canvas.viewport(),Qt.LeftButton,pos=end); qapp.processEvents()
    after=np.array(e.candidates[1]['corners'])
    assert after[:2]-before[:2]==pytest.approx(np.tile([10,12],(2,1)),abs=2)
    assert after[2:]==pytest.approx(before[2:])
    assert not e.points and not e.review.isChecked()
    e._undo_edit(); assert np.array(e.candidates[1]['corners'])==pytest.approx(before)
    assert e.naming_scroll.isAncestorOf(e.level)
    e.close()


def test_candidate_endpoint_body_and_roi_corner_mouse_edits(qapp):
    from PySide6.QtCore import Qt,QPointF
    from PySide6.QtTest import QTest
    from modules.ai_imaging.eagle_eye_total_spine.widget import ProjectionEditor
    e=ProjectionEditor('coronal'); e.resize(1500,900); e.show(); e.accept_image(view()['image'])
    e._set_region([100,50,400,700])
    e.accept_candidates({'candidates':[{'corners':list(body(240,300,height=80).values())}]})
    e.canvas.fit(); qapp.processEvents()
    def drag(a,b):
        start=e.canvas.mapFromScene(QPointF(*a)); end=e.canvas.mapFromScene(QPointF(*b))
        QTest.mousePress(e.canvas.viewport(),Qt.LeftButton,pos=start)
        QTest.mouseMove(e.canvas.viewport(),end,delay=20)
        QTest.mouseRelease(e.canvas.viewport(),Qt.LeftButton,pos=end); qapp.processEvents()
    before=np.array(e.candidates[0]['corners']); drag(before[1],before[1]+[0,10])
    after=np.array(e.candidates[0]['corners'])
    assert after[1,1]>before[1,1]+7 and after[0]==pytest.approx(before[0])
    # Click below the badge to translate the whole body.
    center=after.mean(0)+[-5,15]; drag(center,center+[10,12])
    shifted=np.array(e.candidates[0]['corners'])
    assert shifted-after==pytest.approx(np.tile([10,12],(4,1)),abs=2)
    drag([100,50],[90,40])
    assert e.region[:2]==pytest.approx([90,40],abs=2)
    assert not e.candidates and not e.points
    e.close()


def test_invalid_candidate_edit_preserves_geometry_and_selection(qapp):
    from modules.ai_imaging.eagle_eye_total_spine.widget import ProjectionEditor
    e=ProjectionEditor('coronal'); e.accept_image(view()['image'])
    original=list(body(240,100).values())
    e.accept_candidates({'candidates':[{'corners':original}]})
    e._candidate_changed(0,[[-1,-1],*original[1:]])
    assert e.candidates[0]['corners']==original and not e._undo
    e.close()


def test_roi_click_or_invalid_resize_keeps_candidates_and_restores_handles(qapp):
    from modules.ai_imaging.eagle_eye_total_spine.widget import ProjectionEditor
    e=ProjectionEditor('coronal'); e.accept_image(view()['image'])
    e._set_region([100,50,400,700])
    e.accept_candidates({'candidates':[{'corners':list(body(240,300).values())}]})
    e._set_region(list(e.region)); assert len(e.candidates)==1
    e._region_handles[0].setPos(450,800)
    assert not e._set_region([450,800,400,700])
    assert e._region_handles[0].pos().x()==100 and len(e.candidates)==1
    e.close()
