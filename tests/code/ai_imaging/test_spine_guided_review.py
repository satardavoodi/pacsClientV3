"""Selected-measurement workflow with synthetic images only."""
from test_eagle_eye_total_spine import view, qapp


def test_guide_does_not_require_whole_spine_and_scopes_evidence():
    from modules.ai_imaging.eagle_eye_total_spine.guided_review import review_tasks
    v = view()
    tasks = {t['kind']: t for t in review_tasks(v)}
    assert tasks['cobb']['status'] == 'Needs review'
    assert tasks['rotation']['status'] == 'Missing data'
    assert tasks['balance']['status'] == 'Missing data'
    before = tasks['cobb']['signature']
    v['pedicles'] = {'T8': {'image_left': [290, 400]}}
    assert next(t for t in review_tasks(v) if t['kind'] == 'cobb')['signature'] == before
    v['points']['T4']['superior_left'][0] += 5
    assert next(t for t in review_tasks(v) if t['kind'] == 'cobb')['signature'] != before


def test_editor_guides_only_missing_reference(qapp):
    from modules.ai_imaging.eagle_eye_total_spine.widget import ProjectionEditor
    e = ProjectionEditor('coronal'); e.accept_image(view()['image'])
    e.points = view()['points']; e.curves = view()['curves']; e.recalculate()
    guide = e.guide
    row = next(i for i,t in enumerate(guide.tasks) if t['kind'] == 'balance')
    guide.results.selectRow(row)
    guide.edit.click()
    assert e.canvas.manual_target == ('balance', 'Sacral center')
    assert not guide.confirm.isEnabled()
    assert 'S1' in guide.instruction.text()
    assert guide.moved_section == 'Correct endplates'
    e.close()


def test_guided_confirmation_is_invalidated_only_by_its_evidence(qapp):
    from modules.ai_imaging.eagle_eye_total_spine.widget import ProjectionEditor
    from modules.ai_imaging.eagle_eye_total_spine.guided_review import review_tasks
    e = ProjectionEditor('coronal'); v = view(); e.accept_image(v['image'])
    e.points = v['points']; e.curves = v['curves']; e.confirm.setChecked(True)
    e.recalculate()
    row = next(i for i,t in enumerate(e.guide.tasks) if t['kind'] == 'apex')
    e.guide.results.selectRow(row); e.guide.confirm.click()
    status = lambda: next(t['status'] for t in review_tasks(e.snapshot()) if t['kind'] == 'apex')
    assert status() == 'Ready'
    e.pedicles['T8'] = {'image_left': [280, 400]}; e.invalidate()
    assert status() == 'Ready'
    e.points['T8']['superior_left'][0] += 5; e.invalidate()
    assert status() == 'Needs review'
    e.close()


def test_apex_update_keeps_confirmed_endplates(qapp):
    from modules.ai_imaging.eagle_eye_total_spine.widget import ProjectionEditor
    from modules.ai_imaging.eagle_eye_total_spine.review_workflow import curve_is_reviewed
    e = ProjectionEditor('coronal'); v = view(); e.accept_image(v['image'])
    e.points = v['points']; e.curves = v['curves']; e.confirm.setChecked(True)
    e.recalculate(); e.table.selectRow(0); e._confirm_curve()
    e.apex.setCurrentText('Not assessed'); e._update_curve()
    assert curve_is_reviewed(e.snapshot(), e.curves[0])
    e.close()
